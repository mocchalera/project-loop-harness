from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from . import __version__
from .contracts.progress_receipt import (
    EXECUTION_BINDING_CONTRACT_VERSION,
    PROGRESS_RECEIPT_CONTRACT_VERSION,
    finalize_progress_receipt,
    serialized_progress_receipt,
    validate_progress_receipt,
)
from .db import connect, connect_mutation, table_exists
from .errors import EXIT_USAGE, DataStoreError, InvalidInputError, PclError
from .evidence import (
    insert_evidence_link,
    require_healthy_terminal_evidence,
)
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .strict_evidence import (
    StrictFileWrite,
    strict_read_canonical_file,
    strict_remove_written_file,
    strict_write_new_canonical_file,
)
from .target_resolver import (
    TaskGoalTargetNotFoundError,
    resolve_existing_task_goal,
)
from .timeutil import utc_now_iso


PROGRESS_RECEIPT_EVIDENCE_TYPE = "progress_receipt"
PROGRESS_RECEIPT_LINK_ROLE = "progress_receipt"
PROGRESS_RECEIPT_EVENT_TYPE = "progress_receipt_recorded"
PROGRESS_STATUSES = {"started", "completed", "blocked"}


class ExecutionBindingUnrelatedRootError(PclError):
    def __init__(
        self,
        *,
        canonical_root: Path,
        execution_root: Path,
        canonical_common_dir: str | None,
        execution_common_dir: str | None,
    ) -> None:
        super().__init__(
            message=(
                "The execution root is not part of the canonical project's Git "
                "common directory."
            ),
            code="execution_binding_unrelated_root",
            exit_code=EXIT_USAGE,
            details={
                "canonical_root": str(canonical_root),
                "execution_root": str(execution_root),
                "canonical_common_dir": canonical_common_dir,
                "execution_common_dir": execution_common_dir,
            },
        )


class ProgressEvidenceTargetMismatchError(PclError):
    def __init__(
        self,
        *,
        evidence_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        super().__init__(
            message=(
                f"Evidence {evidence_id} is not linked to "
                f"{target_type} {target_id}."
            ),
            code="progress_evidence_target_mismatch",
            exit_code=EXIT_USAGE,
            details={
                "evidence_id": evidence_id,
                "target": {"type": target_type, "id": target_id},
            },
        )


def record_progress(
    paths: ProjectPaths,
    *,
    target_type: str,
    target_id: str,
    milestone: str,
    status: str,
    evidence_id: str | None = None,
    blockers: list[str] | None = None,
    execution_root: str | None = None,
    cockpit_task_id: str | None = None,
    cockpit_report_sequence: int | None = None,
    cockpit_report_ref: str | None = None,
    ci_provider: str | None = None,
    ci_run_id: str | None = None,
    ci_run_url: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    milestone = milestone.strip()
    if not milestone:
        raise InvalidInputError(
            "--milestone must not be empty.",
            details={"field": "milestone"},
        )
    status = status.strip()
    if status not in PROGRESS_STATUSES:
        raise InvalidInputError(
            f"Invalid progress status: {status}",
            details={"field": "status", "allowed": sorted(PROGRESS_STATUSES)},
        )
    normalized_blockers = _normalized_blockers(blockers or [])
    if status == "blocked" and not normalized_blockers:
        raise InvalidInputError(
            "Blocked progress requires at least one --blocker.",
            details={"field": "blocker", "status": status},
        )
    binding = build_execution_binding(
        paths,
        execution_root=execution_root,
        cockpit_task_id=cockpit_task_id,
        cockpit_report_sequence=cockpit_report_sequence,
        cockpit_report_ref=cockpit_report_ref,
        ci_provider=ci_provider,
        ci_run_id=ci_run_id,
        ci_run_url=ci_run_url,
    )
    timestamp = (now or utc_now_iso()).replace("+00:00", "Z")
    conn = connect_mutation(paths)
    written: StrictFileWrite | None = None
    try:
        _require_target(
            conn,
            target_type=target_type,
            target_id=target_id,
        )
        latest_evidence = (
            _validated_target_evidence(
                paths,
                conn,
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
            )
            if evidence_id is not None
            else None
        )
        progress_evidence_id = next_prefixed_id(conn, "evidence", "E")
        receipt = finalize_progress_receipt(
            {
                "contract_version": PROGRESS_RECEIPT_CONTRACT_VERSION,
                "receipt_id": "pr-sha256:" + "0" * 64,
                "producer": {
                    "name": "project-loop-harness",
                    "version": __version__,
                },
                "generated_at": timestamp,
                "target": {"type": target_type, "id": target_id},
                "milestone": milestone,
                "status": status,
                "execution_binding": binding,
                "latest_valid_evidence": latest_evidence,
                "residual_blockers": normalized_blockers,
            }
        )
        validation = validate_progress_receipt(receipt)
        if not validation.ok:
            raise DataStoreError(
                "Generated progress receipt failed validation.",
                details={"errors": list(validation.errors)},
            )
        content = serialized_progress_receipt(receipt).encode("utf-8")
        artifact_sha256 = hashlib.sha256(content).hexdigest()
        directory = paths.evidence_dir / "progress-receipts"
        artifact_path = directory / f"{progress_evidence_id}.json"
        written = strict_write_new_canonical_file(
            artifact_path,
            expected_parent=directory,
            content=content,
        )
        relative_path = str(artifact_path.relative_to(paths.root))
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                progress_evidence_id,
                PROGRESS_RECEIPT_EVIDENCE_TYPE,
                relative_path,
                "pcl progress record",
                f"{status.title()} milestone {milestone} for {target_type} {target_id}.",
                timestamp,
            ),
        )
        insert_evidence_link(
            conn,
            evidence_id=progress_evidence_id,
            target_type=target_type,
            target_id=target_id,
            link_role=PROGRESS_RECEIPT_LINK_ROLE,
            created_at=timestamp,
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=PROGRESS_RECEIPT_EVENT_TYPE,
            entity_type=target_type,
            entity_id=target_id,
            payload={
                "artifact_sha256": artifact_sha256,
                "evidence_id": progress_evidence_id,
                "receipt_id": receipt["receipt_id"],
                "target": receipt["target"],
            },
        )
        conn.commit()
        return {
            "artifact_path": relative_path,
            "artifact_sha256": artifact_sha256,
            "evidence_id": progress_evidence_id,
            "event_id": event_id,
            "receipt": receipt,
        }
    except BaseException as exc:
        committed = bool(getattr(conn, "_authoritative_commit_completed", False))
        if not committed:
            try:
                conn.rollback()
            except BaseException:
                pass
            if written is not None:
                strict_remove_written_file(written)
        if isinstance(exc, (OSError, sqlite3.Error)):
            raise DataStoreError(f"Could not record progress receipt: {exc}") from exc
        raise
    finally:
        conn.close()


def build_execution_binding(
    paths: ProjectPaths,
    *,
    execution_root: str | None,
    cockpit_task_id: str | None,
    cockpit_report_sequence: int | None,
    cockpit_report_ref: str | None,
    ci_provider: str | None,
    ci_run_id: str | None,
    ci_run_url: str | None,
) -> dict[str, Any]:
    canonical_root = paths.root.resolve()
    execution_path = Path(execution_root).resolve() if execution_root else canonical_root
    if not execution_path.is_dir():
        raise InvalidInputError(
            "--execution-root must be an existing directory.",
            details={"field": "execution_root", "path": str(execution_path)},
        )
    cockpit = _cockpit_binding(
        task_id=cockpit_task_id,
        report_sequence=cockpit_report_sequence,
        report_ref=cockpit_report_ref,
    )
    ci = _ci_binding(
        provider=ci_provider,
        run_id=ci_run_id,
        run_url=ci_run_url,
    )
    canonical_git = _git_metadata(canonical_root)
    execution_git = _git_metadata(execution_path)
    if canonical_git is None and execution_git is None:
        if canonical_root != execution_path:
            raise ExecutionBindingUnrelatedRootError(
                canonical_root=canonical_root,
                execution_root=execution_path,
                canonical_common_dir=None,
                execution_common_dir=None,
            )
        git = {
            "available": False,
            "worktree_root": None,
            "common_dir": None,
            "head_revision": None,
            "branch": None,
            "detached": None,
            "relationship": "non_git",
        }
    elif (
        canonical_git is None
        or execution_git is None
        or canonical_git["common_dir"] != execution_git["common_dir"]
    ):
        raise ExecutionBindingUnrelatedRootError(
            canonical_root=canonical_root,
            execution_root=execution_path,
            canonical_common_dir=(
                None if canonical_git is None else str(canonical_git["common_dir"])
            ),
            execution_common_dir=(
                None if execution_git is None else str(execution_git["common_dir"])
            ),
        )
    else:
        relationship = (
            "same_worktree"
            if canonical_git["worktree_root"] == execution_git["worktree_root"]
            else "linked_worktree"
        )
        git = {
            "available": True,
            "worktree_root": str(execution_git["worktree_root"]),
            "common_dir": str(execution_git["common_dir"]),
            "head_revision": execution_git["head_revision"],
            "branch": execution_git["branch"],
            "detached": execution_git["detached"],
            "relationship": relationship,
        }
    return {
        "contract_version": EXECUTION_BINDING_CONTRACT_VERSION,
        "canonical_root": str(canonical_root),
        "execution_root": str(execution_path),
        "git": git,
        "cockpit": cockpit,
        "ci": ci,
    }


def assess_progress_receipt(
    paths: ProjectPaths,
    *,
    evidence_id: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "artifact_health": "ok",
        "contract_version": PROGRESS_RECEIPT_CONTRACT_VERSION,
        "evidence_id": evidence_id,
    }
    conn = connect(paths.db_path)
    try:
        evidence = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        links = conn.execute(
            """
            SELECT target_type, target_id, link_role
            FROM evidence_links
            WHERE evidence_id = ?
            ORDER BY created_at, target_type, target_id, link_role
            """,
            (evidence_id,),
        ).fetchall()
        events = conn.execute(
            """
            SELECT entity_type, entity_id, payload_json
            FROM events
            WHERE event_type = ?
            ORDER BY sequence DESC
            """,
            (PROGRESS_RECEIPT_EVENT_TYPE,),
        ).fetchall()
    finally:
        conn.close()
    anchor = None
    event = None
    for candidate_event in events:
        try:
            candidate = json.loads(str(candidate_event["payload_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("evidence_id") == evidence_id:
            anchor = candidate
            event = candidate_event
            break
    if anchor is None or event is None:
        return {
            **base,
            "artifact_health": "anchor_missing",
            "reason": "A matching progress_receipt_recorded event is absent.",
        }
    target = anchor.get("target")
    if (
        not isinstance(target, dict)
        or target.get("type") not in {"task", "goal"}
        or not isinstance(target.get("id"), str)
        or str(event["entity_type"]) != target["type"]
        or str(event["entity_id"]) != target["id"]
    ):
        return {
            **base,
            "artifact_health": "anchor_target_mismatch",
            "reason": "The event target and progress anchor disagree.",
        }
    if evidence is None:
        return {
            **base,
            "artifact_health": "evidence_missing",
            "reason": "The anchored Evidence row is absent.",
        }
    if str(evidence["type"]) != PROGRESS_RECEIPT_EVIDENCE_TYPE:
        return {
            **base,
            "artifact_health": "wrong_evidence_type",
            "reason": "The anchored Evidence row has the wrong type.",
        }
    matching_links = [
        link
        for link in links
        if str(link["link_role"]) == PROGRESS_RECEIPT_LINK_ROLE
    ]
    if len(matching_links) != 1 or (
        str(matching_links[0]["target_type"]) != target["type"]
        or str(matching_links[0]["target_id"]) != target["id"]
    ):
        return {
            **base,
            "artifact_health": "target_link_mismatch",
            "reason": "The progress Evidence link and event target disagree.",
        }
    directory = paths.evidence_dir / "progress-receipts"
    artifact_path = paths.root / str(evidence["path"])
    if (
        artifact_path.parent != directory
        or artifact_path.name != f"{evidence_id}.json"
    ):
        return {
            **base,
            "artifact_health": "wrong_evidence_path",
            "reason": "The Evidence path is not the canonical progress receipt path.",
        }
    read = strict_read_canonical_file(
        artifact_path,
        expected_parent=directory,
    )
    if not read.ok or read.content is None:
        return {
            **base,
            "artifact_health": f"artifact_{read.status}",
            "reason": read.detail or f"Strict artifact read failed: {read.status}.",
        }
    artifact_sha256 = hashlib.sha256(read.content).hexdigest()
    if artifact_sha256 != anchor.get("artifact_sha256"):
        return {
            **base,
            "artifact_health": "artifact_hash_mismatch",
            "artifact_sha256": artifact_sha256,
            "recorded_artifact_sha256": anchor.get("artifact_sha256"),
            "reason": "Artifact bytes do not match the immutable event anchor.",
        }
    try:
        receipt = json.loads(read.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            **base,
            "artifact_health": "artifact_invalid",
            "reason": str(exc),
        }
    validation = validate_progress_receipt(receipt)
    if not validation.ok:
        return {
            **base,
            "artifact_health": "artifact_invalid",
            "reason": "; ".join(validation.errors),
        }
    if receipt.get("target") != target:
        return {
            **base,
            "artifact_health": "artifact_target_mismatch",
            "reason": "The receipt target and event target disagree.",
        }
    if receipt.get("receipt_id") != anchor.get("receipt_id"):
        return {
            **base,
            "artifact_health": "receipt_id_mismatch",
            "reason": "The receipt ID and event anchor disagree.",
        }
    return {
        **base,
        "artifact_path": str(evidence["path"]),
        "artifact_sha256": artifact_sha256,
        "payload": receipt,
        "target": target,
    }


def latest_progress_context(
    paths: ProjectPaths,
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any] | None:
    conn = connect(paths.db_path)
    try:
        if not table_exists(conn, "evidence_links"):
            return None
        row = conn.execute(
            """
            SELECT evidence.id, evidence.path
            FROM evidence_links
            JOIN evidence ON evidence.id = evidence_links.evidence_id
            WHERE evidence_links.target_type = ?
              AND evidence_links.target_id = ?
              AND evidence_links.link_role = ?
            ORDER BY evidence.created_at DESC, evidence.id DESC
            LIMIT 1
            """,
            (
                target_type,
                target_id,
                PROGRESS_RECEIPT_LINK_ROLE,
            ),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    evidence_id = str(row["id"])
    assessment = assess_progress_receipt(paths, evidence_id=evidence_id)
    if assessment["artifact_health"] != "ok":
        return {
            "artifact_health": assessment["artifact_health"],
            "artifact_path": str(row["path"]),
            "evidence_id": evidence_id,
            "reason": assessment.get("reason"),
            "status": "invalid",
        }
    return {
        "artifact_health": "ok",
        "artifact_path": assessment["artifact_path"],
        "artifact_sha256": assessment["artifact_sha256"],
        "evidence_id": evidence_id,
        "receipt": assessment["payload"],
        "status": "valid",
    }


def _require_target(
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
) -> None:
    try:
        target = resolve_existing_task_goal(conn, target_id)
    except TaskGoalTargetNotFoundError as exc:
        raise InvalidInputError(
            f"Progress target does not exist: {target_id}",
            details={"target": target_id, "target_type": exc.target_type},
        ) from exc
    if target.type != target_type:
        raise InvalidInputError(
            f"Progress target type does not match {target_id}.",
            details={
                "target": target_id,
                "expected_type": target_type,
                "actual_type": target.type,
            },
        )


def _validated_target_evidence(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
) -> dict[str, str]:
    row = require_healthy_terminal_evidence(
        paths,
        conn,
        evidence_id=evidence_id,
        error_code="progress_evidence_invalid",
    )
    link = conn.execute(
        """
        SELECT link_role
        FROM evidence_links
        WHERE evidence_id = ?
          AND target_type = ?
          AND target_id = ?
          AND link_role != 'supersedes'
        ORDER BY created_at, link_role
        LIMIT 1
        """,
        (evidence_id, target_type, target_id),
    ).fetchone()
    if link is None:
        raise ProgressEvidenceTargetMismatchError(
            evidence_id=evidence_id,
            target_type=target_type,
            target_id=target_id,
        )
    return {
        "evidence_id": str(row["id"]),
        "type": str(row["type"]),
        "created_at": str(row["created_at"]),
        "link_role": str(link["link_role"]),
    }


def _normalized_blockers(blockers: list[str]) -> list[str]:
    result: list[str] = []
    for blocker in blockers:
        value = blocker.strip()
        if not value:
            raise InvalidInputError(
                "--blocker must not be empty.",
                details={"field": "blocker"},
            )
        if value not in result:
            result.append(value)
    return result


def _cockpit_binding(
    *,
    task_id: str | None,
    report_sequence: int | None,
    report_ref: str | None,
) -> dict[str, Any] | None:
    task_id = _clean_optional(task_id)
    report_ref = _clean_optional(report_ref)
    if task_id is None:
        if report_sequence is not None or report_ref is not None:
            raise InvalidInputError(
                "Cockpit report fields require --cockpit-task-id.",
                details={"field": "cockpit_task_id"},
            )
        return None
    if report_sequence is not None and report_sequence < 0:
        raise InvalidInputError(
            "--cockpit-report-seq must be non-negative.",
            details={"field": "cockpit_report_sequence"},
        )
    return {
        "task_id": task_id,
        "report_sequence": report_sequence,
        "report_ref": report_ref,
    }


def _ci_binding(
    *,
    provider: str | None,
    run_id: str | None,
    run_url: str | None,
) -> dict[str, str | None] | None:
    provider = _clean_optional(provider)
    run_id = _clean_optional(run_id)
    run_url = _clean_optional(run_url)
    if provider is None and run_id is None and run_url is None:
        return None
    if provider is None or run_id is None:
        raise InvalidInputError(
            "CI binding requires both --ci-provider and --ci-run-id.",
            details={"field": "ci", "provider": provider, "run_id": run_id},
        )
    return {
        "provider": provider,
        "run_id": run_id,
        "run_url": run_url,
    }


def _git_metadata(root: Path) -> dict[str, Any] | None:
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return None
    worktree = _git(root, "rev-parse", "--show-toplevel")
    common_dir = _git(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    head = _git(root, "rev-parse", "HEAD")
    if not worktree or not common_dir or not head:
        raise InvalidInputError(
            "Git execution binding requires a resolvable worktree, common dir, and HEAD.",
            details={"root": str(root)},
        )
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    return {
        "worktree_root": Path(worktree).resolve(),
        "common_dir": Path(common_dir).resolve(),
        "head_revision": head,
        "branch": branch or None,
        "detached": not bool(branch),
    }


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
