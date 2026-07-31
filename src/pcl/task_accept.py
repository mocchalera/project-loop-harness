from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
from typing import Any

from .command_domain import _guard_feature_done
from .db import SCHEMA_VERSION, connect, connect_mutation
from .direct_spec import DirectSpecError, DirectSpecRootBinding, secure_read_project_artifact
from .errors import (
    EXIT_DATA_ERROR,
    EXIT_NOT_INITIALIZED,
    EXIT_RECOVERABLE_PENDING,
    EXIT_USAGE,
    ProjectionPendingError,
)
from .events import append_event
from .locks import project_operation_lock, require_live_exclusive_project_operation_capability
from .outbox import canonical_event_bytes, canonical_event_record
from .paths import ProjectPaths
from .prefixed_ids import decimal_sort_key, increment_decimal_text
from .project_config import dashboard_auto_render
from .renderer import _render_dashboard_with_lock
from .tasks import task_terminal_readiness_for_row
from .test_faults import crash_if_requested
from .timeutil import utc_now_iso
from .validators import collect_authoritative_admission_findings, validate_project


TASK_ACCEPT_CONTRACT_VERSION = "task-accept-envelope/v1"
TASK_ACCEPT_REQUEST_VERSION = "task-accept-request/v1"
TASK_ACCEPT_PREIMAGE_VERSION = "task-accept-bundle-preimage/v1"
TASK_ACCEPT_RECEIPT_VERSION = "task-acceptance-receipt/v1"
TASK_ACCEPT_MAX_ARTIFACT_BYTES = 10_000_000
TASK_ACCEPT_MAX_TESTS = 96
TASK_ACCEPT_MAX_PATH_BYTES = 4_096
TASK_ACCEPT_MAX_COMMAND_BYTES = 8_192
TASK_ACCEPT_MAX_SUMMARY_BYTES = 65_536
TASK_ACCEPT_MAX_EVENT_PAYLOAD_BYTES = 131_072
_TASK_ID = re.compile(r"^T-[0-9]{4,4096}$")
_TEST_ID = re.compile(r"^TC-[0-9]{4,4096}$")
_EVIDENCE_ID = re.compile(r"^E-([0-9]+)$")
_GENERATION_DIR = re.compile(r"^generation-([0-9]{4,})$")


@dataclass
class _Abort(Exception):
    code: str
    message: str
    exit_code: int = 1
    phase: str = "precommit"
    safe_to_retry_original: bool = False
    prior_acceptance_verified: bool = False
    safe_retry_action: str | None = None


@dataclass(frozen=True)
class _Artifact:
    relative_path: str
    content: bytes
    sha256: str
    size_bytes: int
    root_binding: DirectSpecRootBinding


@dataclass(frozen=True)
class _Generation:
    number: int
    directory: Path
    record: dict[str, Any]
    record_sha256: str
    created: bool


@dataclass(frozen=True)
class _LedgerState:
    generations: tuple[_Generation, ...]
    accepted_count: int
    tail_recovery_generation: int


def canonical_task_accept_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def accept_task(
    paths: ProjectPaths,
    *,
    task_id: str,
    artifact_path: str,
    command: str,
    summary: str,
    copy_files: bool,
    test_ids: list[str],
) -> dict[str, Any]:
    """Atomically accept one Task through the fixed P1-B surface."""

    envelope = _envelope()
    envelope["mode"] = "fresh"
    artifact: _Artifact | None = None
    try:
        normalized = _validate_request_inputs(
            task_id=task_id,
            artifact_path=artifact_path,
            command=command,
            summary=summary,
            copy_files=copy_files,
            test_ids=test_ids,
        )
        if not paths.loop_dir.is_dir() or not paths.db_path.is_file():
            raise _Abort(
                "task_accept_not_initialized",
                "Project Loop Harness is not initialized at the requested root.",
                EXIT_NOT_INITIALIZED,
                "installation",
                True,
            )
        artifact = _read_artifact(paths, normalized["artifact_path"])
        envelope["phase"] = "artifact_preflight"
        result = _accept_under_root_binding(
            paths,
            artifact=artifact,
            task_id=normalized["task_id"],
            command=normalized["command"],
            summary=normalized["summary"],
            test_ids=normalized["test_ids"],
        )
        result["teardown"] = {"status": "complete", "error": None}
        return result
    except _Abort as exc:
        return _error_envelope(
            envelope,
            code=exc.code,
            message=exc.message,
            exit_code=exc.exit_code,
            phase=exc.phase,
            safe_to_retry_original=exc.safe_to_retry_original,
            prior_acceptance_verified=exc.prior_acceptance_verified,
            safe_retry_action=exc.safe_retry_action,
        )
    except DirectSpecError:
        return _error_envelope(
            envelope,
            code="task_accept_artifact_preflight_failed",
            message="The acceptance artifact could not be read safely.",
            exit_code=EXIT_USAGE,
            phase="artifact_preflight",
            safe_to_retry_original=True,
        )
    except Exception:
        return _error_envelope(
            envelope,
            code="task_accept_internal_error",
            message="Atomic Task Accept failed before a commit could be confirmed.",
            exit_code=EXIT_DATA_ERROR,
            phase=str(envelope.get("phase") or "internal"),
            safe_to_retry_original=False,
        )
    finally:
        if artifact is not None:
            artifact.root_binding.close()


def _validate_request_inputs(
    *,
    task_id: str,
    artifact_path: str,
    command: str,
    summary: str,
    copy_files: bool,
    test_ids: list[str],
) -> dict[str, Any]:
    if not copy_files:
        raise _Abort(
            "task_accept_copy_required",
            "Atomic Task Accept requires --copy.",
            EXIT_USAGE,
            "input",
            True,
        )
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise _Abort(
            "task_accept_invalid_input",
            "Task ID must match T- followed by 4 to 4096 ASCII digits.",
            EXIT_USAGE,
            "input",
            True,
        )
    if not isinstance(test_ids, list) or not test_ids:
        raise _Abort(
            "task_accept_test_required",
            "Atomic Task Accept requires at least one --test.",
            EXIT_USAGE,
            "input",
            True,
        )
    if len(test_ids) > TASK_ACCEPT_MAX_TESTS:
        raise _Abort(
            "task_accept_invalid_input",
            f"Atomic Task Accept supports at most {TASK_ACCEPT_MAX_TESTS} Tests.",
            EXIT_USAGE,
            "input",
            True,
        )
    if any(not isinstance(value, str) or _TEST_ID.fullmatch(value) is None for value in test_ids):
        raise _Abort(
            "task_accept_invalid_input",
            "Every --test value must match TC- followed by 4 to 4096 ASCII digits.",
            EXIT_USAGE,
            "input",
            True,
        )
    if len(set(test_ids)) != len(test_ids):
        raise _Abort(
            "task_accept_invalid_input",
            "Duplicate --test values are not allowed.",
            EXIT_USAGE,
            "input",
            True,
        )
    normalized_path = _normalize_relative_path(artifact_path)
    command = _bounded_nonempty_utf8(command, "command", TASK_ACCEPT_MAX_COMMAND_BYTES)
    summary = _bounded_nonempty_utf8(summary, "summary", TASK_ACCEPT_MAX_SUMMARY_BYTES)
    return {
        "task_id": task_id,
        "test_ids": sorted(test_ids, key=_prefixed_id_sort_key),
        "artifact_path": normalized_path,
        "command": command,
        "summary": summary,
    }


def _normalize_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise _Abort(
            "task_accept_invalid_input",
            "--artifact must be a non-empty project-relative path.",
            EXIT_USAGE,
            "input",
            True,
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _Abort(
            "task_accept_invalid_input",
            "--artifact must be valid UTF-8.",
            EXIT_USAGE,
            "input",
            True,
        ) from exc
    path = PurePosixPath(value)
    if (
        len(encoded) > TASK_ACCEPT_MAX_PATH_BYTES
        or path.is_absolute()
        or value != path.as_posix()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\x00" in value
    ):
        raise _Abort(
            "task_accept_invalid_input",
            "--artifact must be a normalized project-relative POSIX path.",
            EXIT_USAGE,
            "input",
            True,
        )
    return value


def _bounded_nonempty_utf8(value: str, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Abort(
            "task_accept_invalid_input",
            f"--{field} must not be empty.",
            EXIT_USAGE,
            "input",
            True,
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _Abort(
            "task_accept_invalid_input",
            f"--{field} must be valid UTF-8.",
            EXIT_USAGE,
            "input",
            True,
        ) from exc
    if len(encoded) > limit:
        raise _Abort(
            "task_accept_invalid_input",
            f"--{field} exceeds the {limit}-byte limit.",
            EXIT_USAGE,
            "input",
            True,
        )
    return value.strip()


def _read_artifact(paths: ProjectPaths, relative_path: str) -> _Artifact:
    content, binding = secure_read_project_artifact(
        paths,
        relative_path,
        max_bytes=TASK_ACCEPT_MAX_ARTIFACT_BYTES,
    )
    return _Artifact(
        relative_path=relative_path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        root_binding=binding,
    )


def _accept_under_root_binding(
    original_paths: ProjectPaths,
    *,
    artifact: _Artifact,
    task_id: str,
    command: str,
    summary: str,
    test_ids: list[str],
) -> dict[str, Any]:
    if not artifact.root_binding.current_matches(original_paths):
        raise _Abort(
            "task_accept_root_changed",
            "The project root changed after artifact preflight.",
            EXIT_DATA_ERROR,
            "root_binding",
        )
    paths = artifact.root_binding.bound_paths()
    result: dict[str, Any] | None = None
    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        require_live_exclusive_project_operation_capability(
            capability,
            loop_dir=paths.loop_dir,
        )
        _verify_artifact_again(paths, artifact)
        result = _accept_locked(
            paths,
            operation_capability=capability,
            artifact=artifact,
            task_id=task_id,
            command=command,
            summary=summary,
            test_ids=test_ids,
        )
    assert result is not None
    return result


def _accept_locked(
    paths: ProjectPaths,
    *,
    operation_capability: object,
    artifact: _Artifact,
    task_id: str,
    command: str,
    summary: str,
    test_ids: list[str],
) -> dict[str, Any]:
    conn = connect_mutation(
        paths,
        exclusive=True,
        operation_capability=operation_capability,
    )
    committed = False
    envelope = _envelope()
    envelope["mode"] = "fresh"
    try:
        now = utc_now_iso()
        admission = collect_authoritative_admission_findings(conn, now=now)
        if not admission.ok:
            raise _Abort(
                "task_accept_admission_failed",
                "Authoritative project admission checks failed.",
                1,
                "admission",
            )
        _require_delivered_outbox(conn)
        prefix = _verified_common_prefix(paths, conn)
        project_instance_id = _project_instance_id(conn)
        graph = _load_graph(conn, task_id=task_id, test_ids=test_ids)
        request, identity = _request_identity(
            project_instance_id=project_instance_id,
            artifact=artifact,
            task_id=task_id,
            feature_id=graph["feature_id"],
            test_ids=test_ids,
            command=command,
            summary=summary,
        )
        envelope["identity"] = identity
        authority_event_id = _authority_event_id(request)
        _require_no_locator_drift(paths, identity)
        existing_authority = conn.execute(
            "SELECT id, sequence, payload_json FROM events WHERE id = ?",
            (authority_event_id,),
        ).fetchone()
        task_accept_events = _task_accept_authority_events(conn, task_id)
        if existing_authority is not None:
            conn.rollback()
            return _verified_replay(
                paths,
                operation_capability=operation_capability,
                request=request,
                identity=identity,
                graph=graph,
                authority_row=existing_authority,
                task_accept_events=task_accept_events,
            )
        if task_accept_events or str(graph["task"]["status"]) == "done":
            raise _Abort(
                "task_accept_task_request_conflict",
                "Task was accepted by a different request.",
                1,
                "request_route",
            )
        _require_fresh_eligibility(graph, test_ids=test_ids)
        generation, evidence_id, fs_effects = _prepare_durable_attempt(
            paths,
            conn,
            request=request,
            identity=identity,
            prefix=prefix,
            artifact=artifact,
        )
        envelope["business_attempt_generation"] = generation.number
        event_plan = _build_event_plan(
            conn,
            request_id=str(identity["request_id"]),
            authority_event_id=authority_event_id,
            evidence_id=evidence_id,
            feature_id=str(graph["feature_id"]),
            task_id=task_id,
            test_ids=test_ids,
            include_passing_event=str(graph["feature"]["status"]) != "passing",
        )
        structural_plan_sha256 = _sha256_canonical(
            {
                "contract_version": "task-accept-structural-plan/v1",
                "pre_hwm": prefix["hwm"],
                "events": [
                    {
                        key: item[key]
                        for key in (
                            "ordinal",
                            "event_id",
                            "sequence",
                            "event_type",
                            "entity_type",
                            "entity_id",
                        )
                    }
                    for item in event_plan
                ],
            }
        )
        member, manifest_path, manifest_sha256, publish_effects = _publish_evidence_files(
            paths,
            artifact=artifact,
            evidence_id=evidence_id,
            request_id=str(identity["request_id"]),
            structural_plan_sha256=structural_plan_sha256,
            allow_exact_adopt=True,
        )
        fs_effects["copies_published"] += publish_effects["copies_published"]
        fs_effects["markers_published"] += publish_effects["markers_published"]
        _verify_artifact_again(paths, artifact)
        business_changes_before = conn.total_changes
        preimage = {
            "contract_version": TASK_ACCEPT_PREIMAGE_VERSION,
            "request_id": identity["request_id"],
            "structural_plan_sha256": structural_plan_sha256,
            "task_id": task_id,
            "feature_id": graph["feature_id"],
            "test_ids": test_ids,
        }
        _stage_evidence(
            conn,
            paths=paths,
            plan_item=event_plan[0],
            evidence_id=evidence_id,
            task_id=task_id,
            feature_id=str(graph["feature_id"]),
            test_ids=test_ids,
            manifest_path=manifest_path,
            member=member,
            command=command,
            summary=summary,
            now=now,
            preimage=preimage,
        )
        plan_cursor = 1
        include_passing = str(graph["feature"]["status"]) != "passing"
        for index, test_id in enumerate(test_ids):
            test_row = graph["tests_by_id"][test_id]
            conn.execute(
                """
                UPDATE test_cases
                SET status = 'passing', evidence_id = ?, updated_at = ?
                WHERE id = ? AND status NOT IN ('passing', 'waived')
                """,
                (evidence_id, now, test_id),
            )
            if conn.execute("SELECT changes()").fetchone()[0] != 1:
                raise _Abort(
                    "task_accept_test_preimage_changed",
                    "A selected Test changed during atomic acceptance.",
                    1,
                    "stage_tests",
                )
            is_final = index == len(test_ids) - 1
            if include_passing and is_final:
                item = event_plan[plan_cursor]
                plan_cursor += 1
                previous_feature_status = str(graph["feature"]["status"])
                conn.execute(
                    "UPDATE features SET status = 'passing', updated_at = ? WHERE id = ? AND status = ?",
                    (now, graph["feature_id"], previous_feature_status),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    raise _Abort(
                        "task_accept_feature_preimage_changed",
                        "Feature changed during atomic acceptance.",
                        1,
                        "stage_feature_passing",
                    )
                _append_planned_event(
                    conn,
                    paths,
                    item,
                    payload={
                        "previous_status": previous_feature_status,
                        "status": "passing",
                        "reason": "test_case_status",
                    },
                    created_at=now,
                )
            item = event_plan[plan_cursor]
            plan_cursor += 1
            _append_planned_event(
                conn,
                paths,
                item,
                payload={
                    "summary": summary,
                    "feature_id": graph["feature_id"],
                    "story_id": test_row["story_id"],
                    "workflow_run_id": None,
                    "evidence_id": evidence_id,
                    "previous_status": test_row["status"],
                    "status": "passing",
                    "feature_status": "passing" if is_final else graph["feature"]["status"],
                    "evidence_mode": "id",
                },
                created_at=now,
            )
        _guard_feature_done(conn, str(graph["feature_id"]))
        feature_item = event_plan[plan_cursor]
        plan_cursor += 1
        previous_feature_status = "passing" if include_passing else str(graph["feature"]["status"])
        conn.execute(
            "UPDATE features SET status = 'done', updated_at = ? WHERE id = ? AND status = ?",
            (now, graph["feature_id"], previous_feature_status),
        )
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise _Abort(
                "task_accept_feature_preimage_changed",
                "Feature changed before the done transition.",
                1,
                "stage_feature_done",
            )
        _append_planned_event(
            conn,
            paths,
            feature_item,
            payload={
                "previous_status": previous_feature_status,
                "status": "done",
                "summary": summary,
                "evidence": "",
                "evidence_id": evidence_id,
                "evidence_mode": "id",
                "source": "manual",
            },
            created_at=now,
        )
        if plan_cursor != len(event_plan) - 1:
            raise _Abort(
                "task_accept_structural_plan_invalid",
                "The staged event plan did not reach the reserved Task event.",
                EXIT_DATA_ERROR,
                "stage",
            )
        _verify_artifact_again(paths, artifact)
        preterminal_event_ids = frozenset(
            str(item["event_id"]) for item in event_plan[:-1]
        )
        validation_result = _validate_candidate_snapshot(
            paths,
            conn,
            overlay_event_ids=preterminal_event_ids,
        )
        if not validation_result.ok:
            raise _Abort(
                "task_accept_validation_failed",
                "The projected final acceptance snapshot failed strict validation.",
                1,
                "final_validation",
            )
        task_row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        assert task_row is not None
        readiness = task_terminal_readiness_for_row(
            paths,
            conn,
            dict(task_row),
            source="task_accept",
            formal_findings=list(validation_result.findings),
        )
        if not readiness.get("terminal_allowed"):
            raise _Abort(
                "task_accept_terminal_readiness_failed",
                "P0-B terminal readiness rejected the projected Task acceptance.",
                1,
                "terminal_readiness",
            )
        task_item = event_plan[-1]
        receipt = {
            "contract_version": TASK_ACCEPT_RECEIPT_VERSION,
            "request_id": identity["request_id"],
            "request_locator": identity["request_locator"],
            "project_instance_id": project_instance_id,
            "task_id": task_id,
            "feature_id": graph["feature_id"],
            "test_ids": test_ids,
            "base_evidence_id": evidence_id,
            "base_evidence_type": "adhoc_artifact",
            "source_sha256": artifact.sha256,
            "source_size": artifact.size_bytes,
            "copy_manifest_sha256": manifest_sha256,
            "structural_plan_sha256": structural_plan_sha256,
            "pre_accept_prefix_hwm": prefix["hwm"]["sequence"],
            "pre_accept_prefix_sha256": prefix["sha256"],
            "current_proof_identity": _current_proof_identity(
                paths,
                conn,
                identity=identity,
                evidence_id=evidence_id,
                evidence_event_id=str(event_plan[0]["event_id"]),
                manifest_path=manifest_path,
                acceptance_event_id=authority_event_id,
                acceptance_event_sequence=int(task_item["sequence"]),
            ),
            "p0b_readiness": readiness,
            "validation_result_sha256": _sha256_canonical(validation_result.to_dict()),
        }
        receipt_bytes = _canonical_bytes(receipt)
        if len(receipt_bytes) > TASK_ACCEPT_MAX_EVENT_PAYLOAD_BYTES:
            raise _Abort(
                "task_accept_receipt_too_large",
                "The Task acceptance receipt exceeds the event payload limit.",
                EXIT_USAGE,
                "receipt",
            )
        post_strict_before = conn.total_changes
        conn.execute(
            """
            UPDATE tasks
            SET status = 'done', updated_at = ?
            WHERE id = ? AND status = 'in_progress' AND updated_at = ?
            """,
            (now, task_id, graph["task"]["updated_at"]),
        )
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise _Abort(
                "task_accept_task_preimage_changed",
                "Task changed after final validation.",
                1,
                "post_strict",
            )
        _append_planned_event(
            conn,
            paths,
            task_item,
            payload={
                "from_status": "in_progress",
                "to_status": "done",
                "reason": summary,
                "terminal_readiness": readiness,
                "task_acceptance": receipt,
            },
            created_at=now,
        )
        if conn.total_changes - post_strict_before != 3:
            raise _Abort(
                "task_accept_post_strict_contract_violation",
                "The post-strict mutation was not exactly Task row, event, and outbox.",
                EXIT_DATA_ERROR,
                "post_strict",
            )
        _verify_final_rows_and_events(
            conn,
            task_id=task_id,
            feature_id=str(graph["feature_id"]),
            test_ids=test_ids,
            evidence_id=evidence_id,
            event_plan=event_plan,
        )
        crash_if_requested("task_accept_before_sqlite_commit")
        try:
            conn.commit()
            committed = True
        except ProjectionPendingError as exc:
            committed = bool(exc.details.get("mutation_committed"))
            if committed:
                return _postcommit_error(
                    envelope,
                    code="task_accept_projection_pending",
                    message="Acceptance committed, but JSONL projection is pending.",
                    identity=identity,
                    authority_event_id=authority_event_id,
                    evidence_id=evidence_id,
                    generation=generation.number,
                    action="pcl audit flush --json",
                    business_changed=True,
                    mutation_committed=True,
                    prior_authoritative_commit=False,
                )
            raise
        except Exception:
            return _commit_outcome_unknown(
                envelope,
                identity=identity,
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=generation.number,
            )
        projection = getattr(conn, "projection_result", None)
        accepted_marker_created = _publish_accepted_marker(
            generation,
            request_id=str(identity["request_id"]),
            authority_event_id=authority_event_id,
            evidence_id=evidence_id,
            receipt_sha256=_sha256_canonical(receipt),
        )
        fs_effects["markers_published"] += int(accepted_marker_created)
        render_receipt = _run_postcommit_render(
            paths,
            operation_capability=operation_capability,
            authority_event_id=authority_event_id,
        )
        if render_receipt["status"] == "pending":
            return _postcommit_error(
                envelope,
                code="task_accept_render_pending",
                message="Acceptance committed, but dashboard rendering is pending.",
                identity=identity,
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=generation.number,
                action="pcl render --json",
                business_changed=True,
                mutation_committed=True,
                prior_authoritative_commit=False,
            )
        business_rows = conn.total_changes - business_changes_before
        envelope.update(
            {
                "authority": {
                    "event_id": authority_event_id,
                    "event_sequence": int(task_item["sequence"]),
                    "evidence_id": evidence_id,
                    "task_id": task_id,
                    "feature_id": graph["feature_id"],
                },
                "business_attempt_generation": generation.number,
                "business_changed": True,
                "changed": True,
                "effects": {
                    "business_rows_changed": business_rows,
                    "copies_published": fs_effects["copies_published"],
                    "events_appended": len(event_plan),
                    "markers_published": fs_effects["markers_published"],
                    "outbox_appended": len(event_plan),
                    "projection_writes": int(getattr(projection, "delivered", 0)),
                    "render_writes": 0 if render_receipt["status"] == "disabled" else 2,
                },
                "exit_code": 0,
                "identity": identity,
                "message": f"Accepted Task {task_id} atomically.",
                "mode": "fresh",
                "mutation_committed": True,
                "ok": True,
                "phase": "complete",
                "prior_acceptance_verified": False,
                "prior_authoritative_commit": False,
                "receipts": {
                    "acceptance": receipt,
                    "projection": None if projection is None else projection.to_dict(),
                    "render": render_receipt,
                },
                "safe_to_retry_original": False,
                "status": "accepted",
                "validation": validation_result.to_dict(),
            }
        )
        return envelope
    except _Abort:
        if not committed and conn.in_transaction:
            conn.rollback()
        raise
    except Exception as exc:
        if not committed and conn.in_transaction:
            conn.rollback()
        if committed:
            return _postcommit_error(
                envelope,
                code="task_accept_tail_pending",
                message="Acceptance committed, but its post-commit tail did not finish.",
                identity=envelope.get("identity") or {},
                authority_event_id=authority_event_id,
                evidence_id=evidence_id,
                generation=int(envelope.get("business_attempt_generation") or 0),
                action="pcl audit flush --json",
                business_changed=True,
                mutation_committed=True,
                prior_authoritative_commit=False,
            )
        raise exc
    finally:
        conn.close()


def _load_graph(conn: sqlite3.Connection, *, task_id: str, test_ids: list[str]) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise _Abort(
            "task_accept_task_not_found",
            "The requested Task does not exist.",
            EXIT_USAGE,
            "graph",
            True,
        )
    feature_id = str(task["related_feature_id"] or "")
    if not feature_id:
        raise _Abort(
            "task_accept_feature_required",
            "Atomic Task Accept requires a Task linked to one Feature.",
            1,
            "graph",
        )
    feature = conn.execute("SELECT * FROM features WHERE id = ?", (feature_id,)).fetchone()
    if feature is None:
        raise _Abort(
            "task_accept_feature_required",
            "The Task-linked Feature is missing.",
            1,
            "graph",
        )
    tests = conn.execute(
        "SELECT * FROM test_cases WHERE feature_id = ? ORDER BY id",
        (feature_id,),
    ).fetchall()
    tests_by_id = {str(row["id"]): row for row in tests}
    missing = [test_id for test_id in test_ids if test_id not in tests_by_id]
    if missing:
        raise _Abort(
            "task_accept_test_scope_mismatch",
            "Every selected Test must belong to the Task-linked Feature.",
            EXIT_USAGE,
            "graph",
            True,
        )
    return {
        "conn": conn,
        "task": task,
        "feature": feature,
        "feature_id": feature_id,
        "tests": tests,
        "tests_by_id": tests_by_id,
    }


def _require_fresh_eligibility(graph: dict[str, Any], *, test_ids: list[str]) -> None:
    task = graph["task"]
    if str(task["status"]) != "in_progress":
        raise _Abort(
            "task_accept_task_not_in_progress",
            "Fresh Atomic Task Accept requires Task status in_progress.",
            1,
            "eligibility",
        )
    selected = set(test_ids)
    non_waived = {str(row["id"]) for row in graph["tests"] if str(row["status"]) != "waived"}
    if selected != non_waived:
        raise _Abort(
            "task_accept_test_closure_mismatch",
            "--test values must exactly cover every non-waived Feature Test.",
            1,
            "eligibility",
        )
    for test_id in test_ids:
        test = graph["tests_by_id"][test_id]
        if str(test["status"]) in {"passing", "waived"}:
            raise _Abort(
                "task_accept_test_not_fresh",
                "Fresh Atomic Task Accept requires each selected Test to be non-passing.",
                1,
                "eligibility",
            )
        story_id = str(test["story_id"] or "")
        story = None if not story_id else graph["conn"].execute(
            "SELECT id, feature_id, status FROM user_stories WHERE id = ?",
            (story_id,),
        ).fetchone()
        if story is None:
            raise _Abort(
                "task_accept_story_required",
                "Every selected Test must link to a Story.",
                1,
                "eligibility",
            )
        if str(story["feature_id"]) != str(graph["feature_id"]):
            raise _Abort(
                "task_accept_story_required",
                "A selected Test Story belongs to a different Feature.",
                1,
                "eligibility",
            )
        if str(story["status"]) not in {"approved", "waived"}:
            raise _Abort(
                "task_accept_story_not_terminal",
                "Every selected Test Story must be approved or waived.",
                1,
                "eligibility",
            )
    active_defect = graph["conn"].execute(
        """
        SELECT id FROM defects
        WHERE feature_id = ? AND status NOT IN ('closed', 'waived')
        ORDER BY id LIMIT 1
        """,
        (graph["feature_id"],),
    ).fetchone()
    if active_defect is not None:
        raise _Abort(
            "task_accept_feature_defect_active",
            "The Task-linked Feature has an active Defect.",
            1,
            "eligibility",
        )


def _request_identity(
    *,
    project_instance_id: str,
    artifact: _Artifact,
    task_id: str,
    feature_id: str,
    test_ids: list[str],
    command: str,
    summary: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    locator_object = {
        "contract_version": "task-accept-locator/v1",
        "project_instance_id": project_instance_id,
        "artifact_locator": artifact.relative_path,
        "task_id": task_id,
        "feature_id": feature_id,
        "test_ids": test_ids,
        "command": command,
        "summary": summary,
        "copy": True,
    }
    request = {
        "contract_version": TASK_ACCEPT_REQUEST_VERSION,
        "project_instance_id": project_instance_id,
        "artifact_locator": artifact.relative_path,
        "source_member": {
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        },
        "task_id": task_id,
        "feature_id": feature_id,
        "test_ids": test_ids,
        "command": command,
        "summary": summary,
        "copy": True,
    }
    request_id = "sha256:" + _framed_sha256("task-accept-request/v1", request)
    locator = "sha256:" + _framed_sha256("task-accept-locator/v1", locator_object)
    return request, {
        "request_id": request_id,
        "request_locator": locator,
        "project_instance_id": project_instance_id,
        "task_id": task_id,
        "feature_id": feature_id,
        "test_ids": test_ids,
        "artifact": {
            "path": artifact.relative_path,
            "sha256": "sha256:" + artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "copy": True,
        },
    }


def _authority_event_id(request: dict[str, Any]) -> str:
    raw = b"pcl:task-accept-anchor:v1\0" + _canonical_bytes(request)
    return "EV-" + hashlib.sha256(raw).hexdigest().upper()


def _prepare_durable_attempt(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    request: dict[str, Any],
    identity: dict[str, Any],
    prefix: dict[str, Any],
    artifact: _Artifact,
) -> tuple[_Generation, str, dict[str, int]]:
    roots = _task_accept_roots(paths)
    for directory in roots.values():
        _ensure_directory(directory)
    locator_hex = str(identity["request_locator"]).removeprefix("sha256:")
    claim_path = roots["claims"] / f"{locator_hex}.claim.json"
    existing_claim = _read_json_if_exists(claim_path)
    if existing_claim is not None:
        if existing_claim.get("request_id") != identity["request_id"]:
            raise _Abort(
                "task_accept_artifact_hash_drift",
                "Artifact bytes changed for an existing literal acceptance request.",
                1,
                "claim",
            )
        evidence_id = str(existing_claim.get("evidence_id") or "")
        if _EVIDENCE_ID.fullmatch(evidence_id) is None:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The durable Task Accept claim is corrupt.",
                EXIT_DATA_ERROR,
                "claim",
            )
        claim_created = False
    else:
        evidence_id = _allocate_evidence_id(paths, conn)
        claim = {
            "contract_version": "task-accept-claim/v1",
            "request_id": identity["request_id"],
            "request_locator": identity["request_locator"],
            "project_instance_id": identity["project_instance_id"],
            "evidence_id": evidence_id,
            "artifact": identity["artifact"],
        }
        claim_created = _publish_json_exclusive(claim_path, claim, allow_exact=False)
    reservation_path = roots["reservations"] / (
        f"{evidence_id.lower()}--{locator_hex}.reservation.json"
    )
    reservation = {
        "contract_version": "task-accept-evidence-reservation/v1",
        "request_id": identity["request_id"],
        "request_locator": identity["request_locator"],
        "evidence_id": evidence_id,
        "source_sha256": artifact.sha256,
        "source_size": artifact.size_bytes,
    }
    reservation_created = _publish_json_exclusive(
        reservation_path,
        reservation,
        allow_exact=existing_claim is not None,
    )
    generation = _prepare_generation(
        roots["requests"] / locator_hex,
        request_id=str(identity["request_id"]),
        request_locator=str(identity["request_locator"]),
        prefix=prefix,
        evidence_id=evidence_id,
    )
    return generation, evidence_id, {
        "copies_published": 0,
        "markers_published": int(claim_created) + int(reservation_created) + int(generation.created),
    }


def _require_no_locator_drift(paths: ProjectPaths, identity: dict[str, Any]) -> None:
    locator_hex = str(identity["request_locator"]).removeprefix("sha256:")
    claim_path = _task_accept_roots(paths)["claims"] / f"{locator_hex}.claim.json"
    claim = _read_json_if_exists(claim_path)
    if claim is not None and claim.get("request_id") != identity["request_id"]:
        raise _Abort(
            "task_accept_artifact_hash_drift",
            "Artifact bytes changed for an existing literal acceptance request.",
            1,
            "request_route",
        )


def _allocate_evidence_id(paths: ProjectPaths, conn: sqlite3.Connection) -> str:
    suffixes: list[str] = []
    for row in conn.execute("SELECT id FROM evidence WHERE id LIKE 'E-%'").fetchall():
        match = _EVIDENCE_ID.fullmatch(str(row["id"]))
        if match:
            suffixes.append(match.group(1))
    roots = _task_accept_roots(paths)
    for candidate in roots["reservations"].glob("e-*--*.reservation.json"):
        prefix = candidate.name.split("--", 1)[0].upper()
        match = _EVIDENCE_ID.fullmatch(prefix)
        if match:
            suffixes.append(match.group(1))
    adhoc_files = paths.evidence_dir / "adhoc-files"
    if adhoc_files.is_dir():
        for candidate in adhoc_files.iterdir():
            match = _EVIDENCE_ID.fullmatch(candidate.name.upper())
            if match:
                suffixes.append(match.group(1))
    maximum = max(suffixes, key=decimal_sort_key) if suffixes else "0"
    return "E-" + increment_decimal_text(maximum.lstrip("0") or "0").zfill(4)


def _prepare_generation(
    request_dir: Path,
    *,
    request_id: str,
    request_locator: str,
    prefix: dict[str, Any],
    evidence_id: str,
) -> _Generation:
    _ensure_directory(request_dir)
    entries = sorted(request_dir.iterdir(), key=lambda path: path.name)
    generations: list[tuple[int, Path, dict[str, Any], str]] = []
    for entry in entries:
        match = _GENERATION_DIR.fullmatch(entry.name)
        if match is None or not entry.is_dir() or entry.is_symlink():
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The Task Accept request ledger contains an invalid entry.",
                EXIT_DATA_ERROR,
                "generation",
            )
        number = int(match.group(1))
        record_path = entry / "generation.json"
        record = _read_json_required(record_path)
        raw = record_path.read_bytes()
        generations.append((number, entry, record, hashlib.sha256(raw).hexdigest()))
    for expected, item in enumerate(generations):
        number, _, record, record_sha256 = item
        previous = None if expected == 0 else generations[expected - 1][3]
        if (
            number != expected
            or record.get("generation") != expected
            or record.get("request_id") != request_id
            or record.get("request_locator") != request_locator
            or record.get("previous_generation_sha256") != previous
        ):
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The Task Accept generation chain is forked or incomplete.",
                EXIT_DATA_ERROR,
                "generation",
            )
        if not isinstance(record_sha256, str):
            raise AssertionError
    current_prefix = {
        "hwm": prefix["hwm"],
        "sha256": prefix["sha256"],
    }
    if generations and generations[-1][2].get("pre_accept_prefix") == current_prefix:
        number, directory, record, digest = generations[-1]
        return _Generation(number, directory, record, digest, False)
    number = len(generations)
    previous_digest = None if not generations else generations[-1][3]
    directory = request_dir / f"generation-{number:04d}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A concurrent or forked Task Accept generation exists.",
            EXIT_DATA_ERROR,
            "generation",
        ) from exc
    record = {
        "contract_version": "task-accept-generation-ledger-entry/v2",
        "generation": number,
        "request_id": request_id,
        "request_locator": request_locator,
        "evidence_id": evidence_id,
        "pre_accept_prefix": current_prefix,
        "previous_generation_sha256": previous_digest,
    }
    _publish_json_exclusive(directory / "generation.json", record, allow_exact=False)
    record_raw = (directory / "generation.json").read_bytes()
    return _Generation(number, directory, record, hashlib.sha256(record_raw).hexdigest(), True)


def _publish_evidence_files(
    paths: ProjectPaths,
    *,
    artifact: _Artifact,
    evidence_id: str,
    request_id: str,
    structural_plan_sha256: str,
    allow_exact_adopt: bool,
) -> tuple[dict[str, Any], str, str, dict[str, int]]:
    copy_root = paths.evidence_dir / "adhoc-files"
    _ensure_directory(copy_root)
    copy_dir = copy_root / evidence_id.lower()
    if not copy_dir.exists():
        copy_dir.mkdir(mode=0o700)
        copy_dir_created = True
    else:
        _require_real_directory(copy_dir)
        if not allow_exact_adopt:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "The reserved Evidence copy directory already exists.",
                EXIT_DATA_ERROR,
                "publish",
            )
        copy_dir_created = False
    stored_name = f"sha256-{artifact.sha256}.artifact"
    stored_path = copy_dir / stored_name
    copy_created = _publish_bytes_exclusive(
        stored_path,
        artifact.content,
        allow_exact=allow_exact_adopt,
    )
    relative_stored_path = stored_path.relative_to(paths.root).as_posix()
    member = {
        "path": artifact.relative_path,
        "path_scope": "in_project",
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "storage_mode": "copied",
        "stored_path": relative_stored_path,
    }
    manifest = {
        "contract_version": "adhoc-evidence/v0",
        "evidence_id": evidence_id,
        "evidence_type": "adhoc_artifact",
        "created_at": utc_now_iso(),
        "members": [member],
    }
    manifest_dir = paths.evidence_dir / "adhoc"
    _ensure_directory(manifest_dir)
    manifest_path = manifest_dir / f"{evidence_id.lower()}-adhoc-v0.json"
    if allow_exact_adopt and manifest_path.exists():
        existing = _read_json_required(manifest_path)
        if (
            existing.get("evidence_id") != evidence_id
            or existing.get("members") != [member]
            or existing.get("evidence_type") != "adhoc_artifact"
        ):
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "An existing Evidence manifest does not match the reserved request.",
                EXIT_DATA_ERROR,
                "publish",
            )
        manifest_created = False
    else:
        manifest_created = _publish_json_exclusive(
            manifest_path,
            manifest,
            allow_exact=False,
        )
    relative_manifest_path = manifest_path.relative_to(paths.root).as_posix()
    return (
        member,
        relative_manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        {
            "copies_published": int(copy_created),
            "markers_published": int(copy_dir_created) + int(manifest_created),
        },
    )


def _stage_evidence(
    conn: sqlite3.Connection,
    *,
    paths: ProjectPaths,
    plan_item: dict[str, Any],
    evidence_id: str,
    task_id: str,
    feature_id: str,
    test_ids: list[str],
    manifest_path: str,
    member: dict[str, Any],
    command: str,
    summary: str,
    now: str,
    preimage: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO evidence(id, type, path, command, summary, created_at, linked_task_id)
        VALUES (?, 'adhoc_artifact', ?, ?, ?, ?, ?)
        """,
        (evidence_id, manifest_path, command, summary, now, task_id),
    )
    links = [
        (evidence_id, "task", task_id, "supporting", now),
        (evidence_id, "feature", feature_id, "acceptance", now),
        *[
            (evidence_id, "test_case", test_id, "acceptance", now)
            for test_id in test_ids
        ],
    ]
    conn.executemany(
        """
        INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        links,
    )
    payload = {
        "contract_version": "adhoc-evidence/v0",
        "evidence_type": "adhoc_artifact",
        "manifest_path": manifest_path,
        "member_count": 1,
        "members": [member],
        "command": command,
        "linked_task_id": task_id,
        "copied_member_count": 1,
        "copied_bytes": int(member["size_bytes"]),
        "task_accept_bundle_preimage": preimage,
    }
    if len(_canonical_bytes(payload)) > TASK_ACCEPT_MAX_EVENT_PAYLOAD_BYTES:
        raise _Abort(
            "task_accept_receipt_too_large",
            "The Evidence event payload exceeds the limit.",
            EXIT_USAGE,
            "stage_evidence",
        )
    _append_planned_event(conn, paths, plan_item, payload=payload, created_at=now)


def _build_event_plan(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    authority_event_id: str,
    evidence_id: str,
    feature_id: str,
    task_id: str,
    test_ids: list[str],
    include_passing_event: bool,
) -> list[dict[str, Any]]:
    hwm = int(conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events").fetchone()[0])
    specs: list[tuple[str, str, str]] = [("adhoc_evidence_recorded", "evidence", evidence_id)]
    for index, test_id in enumerate(test_ids):
        if include_passing_event and index == len(test_ids) - 1:
            specs.append(("feature_status_updated", "feature", feature_id))
        specs.append(("test_case_passed", "test_case", test_id))
    specs.extend(
        [
            ("feature_status_updated", "feature", feature_id),
            ("task_status_changed", "task", task_id),
        ]
    )
    plan: list[dict[str, Any]] = []
    for ordinal, (event_type, entity_type, entity_id) in enumerate(specs):
        event_id = (
            authority_event_id
            if ordinal == len(specs) - 1
            else "EV-"
            + hashlib.sha256(
                f"pcl:task-accept-event:v1\0{request_id}\0{ordinal}".encode("utf-8")
            ).hexdigest().upper()
        )
        outbox_id = "OB-" + hashlib.sha256(
            f"pcl:task-accept-outbox:v1\0{request_id}\0{ordinal}".encode("utf-8")
        ).hexdigest().upper()
        plan.append(
            {
                "ordinal": ordinal,
                "event_id": event_id,
                "outbox_id": outbox_id,
                "sequence": hwm + ordinal + 1,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        )
    event_ids = [item["event_id"] for item in plan]
    outbox_ids = [item["outbox_id"] for item in plan]
    if len(set(event_ids)) != len(event_ids) or len(set(outbox_ids)) != len(outbox_ids):
        raise _Abort(
            "task_accept_id_collision",
            "The deterministic event plan contains an ID collision.",
            EXIT_DATA_ERROR,
            "plan",
        )
    placeholders = ",".join("?" for _ in event_ids)
    if conn.execute(f"SELECT 1 FROM events WHERE id IN ({placeholders}) LIMIT 1", tuple(event_ids)).fetchone():
        raise _Abort("task_accept_id_collision", "A planned event ID already exists.", EXIT_DATA_ERROR, "plan")
    placeholders = ",".join("?" for _ in outbox_ids)
    if conn.execute(f"SELECT 1 FROM outbox_records WHERE id IN ({placeholders}) LIMIT 1", tuple(outbox_ids)).fetchone():
        raise _Abort("task_accept_id_collision", "A planned outbox ID already exists.", EXIT_DATA_ERROR, "plan")
    return plan


def _append_planned_event(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    item: dict[str, Any],
    *,
    payload: dict[str, Any],
    created_at: str,
) -> None:
    event_id = append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type=str(item["event_type"]),
        entity_type=str(item["entity_type"]),
        entity_id=str(item["entity_id"]),
        payload=payload,
        event_id=str(item["event_id"]),
        outbox_id=str(item["outbox_id"]),
        created_at=created_at,
    )
    row = conn.execute("SELECT sequence FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None or int(row["sequence"]) != int(item["sequence"]):
        raise _Abort(
            "task_accept_event_plan_mismatch",
            "The staged event sequence does not match the structural plan.",
            EXIT_DATA_ERROR,
            "stage_event",
        )


def _validate_candidate_snapshot(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    overlay_event_ids: frozenset[str],
):
    return validate_project(
        paths,
        strict=True,
        connection=conn,
        transaction_overlay_event_ids=overlay_event_ids,
    )


def _current_proof_identity(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    identity: dict[str, Any],
    evidence_id: str,
    evidence_event_id: str,
    manifest_path: str,
    acceptance_event_id: str,
    acceptance_event_sequence: int,
) -> dict[str, Any]:
    evidence = conn.execute(
        """
        SELECT id, type, path, command, summary, created_at, linked_task_id
        FROM evidence WHERE id = ?
        """,
        (evidence_id,),
    ).fetchone()
    if evidence is None or str(evidence["path"]) != manifest_path:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence row does not match its manifest.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    if (
        str(evidence["type"]) != "adhoc_artifact"
        or str(evidence["linked_task_id"]) != str(identity["task_id"])
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence has the wrong type or Task target.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    evidence_record = {key: evidence[key] for key in evidence.keys()}
    links = [
        {key: row[key] for key in row.keys()}
        for row in conn.execute(
            """
            SELECT evidence_id, target_type, target_id, link_role, created_at
            FROM evidence_links WHERE evidence_id = ?
            ORDER BY target_type, target_id, link_role
            """,
            (evidence_id,),
        ).fetchall()
    ]
    expected_links = {
        ("task", str(identity["task_id"]), "supporting"),
        ("feature", str(identity["feature_id"]), "acceptance"),
        *{
            ("test_case", str(test_id), "acceptance")
            for test_id in identity["test_ids"]
        },
    }
    actual_links = {
        (str(row["target_type"]), str(row["target_id"]), str(row["link_role"]))
        for row in links
    }
    if actual_links != expected_links:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence link set is incomplete or targets the wrong entity.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    manifest_bytes = _secure_proof_bytes(paths, manifest_path)
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence manifest is invalid.",
            EXIT_DATA_ERROR,
            "current_proof",
        ) from exc
    members = manifest.get("members") if isinstance(manifest, dict) else None
    if (
        not isinstance(members, list)
        or len(members) != 1
        or not isinstance(members[0], dict)
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "Atomic Task Accept requires exactly one healthy Evidence member.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    member = members[0]
    stored_path = member.get("stored_path")
    expected_artifact = identity["artifact"]
    if (
        manifest.get("contract_version") != "adhoc-evidence/v0"
        or manifest.get("evidence_id") != evidence_id
        or manifest.get("evidence_type") != "adhoc_artifact"
        or member.get("path") != expected_artifact["path"]
        or member.get("storage_mode") != "copied"
        or member.get("path_scope") != "in_project"
        or member.get("sha256") != str(expected_artifact["sha256"]).removeprefix("sha256:")
        or member.get("size_bytes") != expected_artifact["size_bytes"]
        or not isinstance(stored_path, str)
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence manifest does not match the request input.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    member_bytes = _secure_proof_bytes(paths, stored_path)
    if (
        len(member_bytes) != expected_artifact["size_bytes"]
        or hashlib.sha256(member_bytes).hexdigest()
        != str(expected_artifact["sha256"]).removeprefix("sha256:")
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The copied acceptance Evidence member is unhealthy.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    evidence_event = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE id = ?
        """,
        (evidence_event_id,),
    ).fetchone()
    if (
        evidence_event is None
        or str(evidence_event["event_type"]) != "adhoc_evidence_recorded"
        or str(evidence_event["entity_type"]) != "evidence"
        or str(evidence_event["entity_id"]) != evidence_id
    ):
        raise _Abort(
            "task_accept_current_proof_invalid",
            "The acceptance Evidence recording event is missing or has the wrong target.",
            EXIT_DATA_ERROR,
            "current_proof",
        )
    suffix_rows = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE sequence >= ? AND sequence < ? ORDER BY sequence
        """,
        (int(evidence_event["sequence"]), acceptance_event_sequence),
    ).fetchall()
    suffix_bytes = b"".join(
        canonical_event_bytes(canonical_event_record(row)) for row in suffix_rows
    )
    proof = {
        "contract_version": "task-accept-current-proof/v1",
        "input_digest": identity["request_id"],
        "evidence_row_sha256": _sha256_canonical(evidence_record),
        "evidence_links_sha256": _sha256_canonical(links),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "member_record_sha256": _sha256_canonical(member),
        "member_sha256": hashlib.sha256(member_bytes).hexdigest(),
        "recording_event_id": evidence_event_id,
        "recording_event_sha256": hashlib.sha256(
            canonical_event_bytes(canonical_event_record(evidence_event))
        ).hexdigest(),
        "recording_event_suffix_sha256": hashlib.sha256(suffix_bytes).hexdigest(),
        "acceptance_hwm": {
            "event_id": acceptance_event_id,
            "sequence": acceptance_event_sequence,
        },
    }
    proof["digest"] = _sha256_canonical(proof)
    return proof


def _secure_proof_bytes(paths: ProjectPaths, relative_path: str) -> bytes:
    try:
        normalized = _normalize_relative_path(relative_path)
        content, binding = secure_read_project_artifact(
            paths,
            normalized,
            max_bytes=TASK_ACCEPT_MAX_ARTIFACT_BYTES,
        )
    except (DirectSpecError, _Abort) as exc:
        raise _Abort(
            "task_accept_current_proof_invalid",
            "A current acceptance proof file could not be read safely.",
            EXIT_DATA_ERROR,
            "current_proof",
        ) from exc
    try:
        return content
    finally:
        binding.close()


def _verify_current_proof_identity(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    receipt: dict[str, Any],
    identity: dict[str, Any],
    evidence_id: str,
    authority_row: sqlite3.Row,
) -> None:
    expected = receipt.get("current_proof_identity")
    if not isinstance(expected, dict):
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance is missing its current-proof identity.",
            1,
            "replay_live",
            False,
            True,
        )
    evidence = conn.execute(
        "SELECT path FROM evidence WHERE id = ?", (evidence_id,)
    ).fetchone()
    try:
        actual = _current_proof_identity(
            paths,
            conn,
            identity=identity,
            evidence_id=evidence_id,
            evidence_event_id=str(expected.get("recording_event_id") or ""),
            manifest_path="" if evidence is None else str(evidence["path"]),
            acceptance_event_id=str(authority_row["id"]),
            acceptance_event_sequence=int(authority_row["sequence"]),
        )
    except _Abort as exc:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance current proof is unhealthy or no longer identical.",
            1,
            "replay_live",
            False,
            True,
        ) from exc
    if actual != expected:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance current-proof identity no longer matches live state.",
            1,
            "replay_live",
            False,
            True,
        )


def _verified_replay(
    paths: ProjectPaths,
    *,
    operation_capability: object,
    request: dict[str, Any],
    identity: dict[str, Any],
    graph: dict[str, Any],
    authority_row: sqlite3.Row,
    task_accept_events: list[sqlite3.Row],
) -> dict[str, Any]:
    envelope = _envelope()
    envelope["mode"] = "replay"
    if len(task_accept_events) != 1 or str(task_accept_events[0]["id"]) != str(authority_row["id"]):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "Task acceptance authority is ambiguous.",
            EXIT_DATA_ERROR,
            "replay_authority",
            False,
            True,
        )
    try:
        payload = json.loads(str(authority_row["payload_json"]))
    except json.JSONDecodeError as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "Task acceptance authority payload is corrupt.",
            EXIT_DATA_ERROR,
            "replay_authority",
            False,
            True,
        ) from exc
    receipt = payload.get("task_acceptance") if isinstance(payload, dict) else None
    if not isinstance(receipt, dict) or receipt.get("request_id") != identity["request_id"]:
        raise _Abort(
            "task_accept_task_request_conflict",
            "The Task authority belongs to a different acceptance request.",
            1,
            "replay_authority",
            False,
            True,
        )
    evidence_id = str(receipt.get("base_evidence_id") or "")
    _verify_current_proof_identity(
        paths,
        graph["conn"],
        receipt=receipt,
        identity=identity,
        evidence_id=evidence_id,
        authority_row=authority_row,
    )
    ledger = _verify_replay_ledger(
        paths,
        identity=identity,
        evidence_id=evidence_id,
        authority_event_id=str(authority_row["id"]),
        receipt_sha256=_sha256_canonical(receipt),
    )
    envelope["tail_recovery_generation"] = ledger.tail_recovery_generation
    if (
        str(graph["task"]["status"]) != "done"
        or str(graph["feature"]["status"]) != "done"
        or any(str(graph["tests_by_id"][test_id]["status"]) != "passing" for test_id in identity["test_ids"])
    ):
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance is no longer the current live Task state.",
            1,
            "replay_live",
            False,
            True,
        )
    expected_links = {
        ("task", identity["task_id"], "supporting"),
        ("feature", identity["feature_id"], "acceptance"),
        *{("test_case", test_id, "acceptance") for test_id in identity["test_ids"]},
    }
    actual_links = {
        (str(row["target_type"]), str(row["target_id"]), str(row["link_role"]))
        for row in graph["conn"].execute(
            "SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchall()
    }
    if actual_links != expected_links:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance Evidence link set is no longer current.",
            1,
            "replay_live",
            False,
            True,
        )
    for target_type, target_id, role in expected_links:
        linked_ids = {
            str(row["evidence_id"])
            for row in graph["conn"].execute(
                """
                SELECT evidence_id FROM evidence_links
                WHERE target_type = ? AND target_id = ? AND link_role = ?
                """,
                (target_type, target_id, role),
            ).fetchall()
        }
        if linked_ids != {evidence_id}:
            raise _Abort(
                "task_accept_replay_not_current",
                "A Task acceptance target now has a different current Evidence link set.",
                1,
                "replay_live",
                False,
                True,
            )
    related_ids = {
        str(identity["task_id"]),
        str(identity["feature_id"]),
        evidence_id,
        *(str(test_id) for test_id in identity["test_ids"]),
    }
    later_related = graph["conn"].execute(
        f"""
        SELECT id FROM events
        WHERE sequence > ?
          AND entity_id IN ({','.join('?' for _ in related_ids)})
        ORDER BY sequence LIMIT 1
        """,
        (int(authority_row["sequence"]), *sorted(related_ids)),
    ).fetchone()
    if later_related is not None:
        raise _Abort(
            "task_accept_replay_not_current",
            "A related Task acceptance entity changed after the authority event.",
            1,
            "replay_live",
            False,
            True,
        )
    validation = _validate_candidate_snapshot(
        paths,
        graph["conn"],
        overlay_event_ids=frozenset(),
    )
    if not validation.ok:
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance no longer passes strict live validation.",
            1,
            "replay_live",
            False,
            True,
        )
    readiness = task_terminal_readiness_for_row(
        paths,
        graph["conn"],
        dict(graph["task"]),
        source="task_accept_replay",
        formal_findings=list(validation.findings),
    )
    if not readiness.get("terminal_allowed"):
        raise _Abort(
            "task_accept_replay_not_current",
            "The prior acceptance no longer passes P0-B current readiness.",
            1,
            "replay_live",
            False,
            True,
        )
    projection_pending = graph["conn"].execute(
        "SELECT COUNT(*) FROM outbox_records WHERE status != 'delivered'"
    ).fetchone()[0]
    if int(projection_pending):
        return _postcommit_error(
            envelope,
            code="task_accept_projection_pending",
            message="Prior acceptance is authoritative, but JSONL projection is pending.",
            identity=identity,
            authority_event_id=str(authority_row["id"]),
            evidence_id=evidence_id,
            generation=0,
            action="pcl audit flush --json",
            business_changed=False,
            mutation_committed=False,
            prior_authoritative_commit=True,
        )
    render = _verify_replay_render(paths, identity=identity)
    if render["status"] == "pending":
        return _postcommit_error(
            envelope,
            code="task_accept_render_pending",
            message="Prior acceptance is authoritative, but dashboard rendering is pending.",
            identity=identity,
            authority_event_id=str(authority_row["id"]),
            evidence_id=evidence_id,
            generation=0,
            action="pcl render --json",
            business_changed=False,
            mutation_committed=False,
            prior_authoritative_commit=True,
        )
    envelope.update(
        {
            "authority": {
                "event_id": str(authority_row["id"]),
                "event_sequence": int(authority_row["sequence"]),
                "evidence_id": evidence_id,
                "task_id": identity["task_id"],
                "feature_id": identity["feature_id"],
            },
            "business_attempt_generation": 0,
            "business_changed": False,
            "changed": False,
            "exit_code": 0,
            "identity": identity,
            "message": f"Task {identity['task_id']} was already accepted by this exact request.",
            "mode": "replay",
            "mutation_committed": False,
            "ok": True,
            "phase": "complete",
            "prior_acceptance_verified": True,
            "prior_authoritative_commit": True,
            "receipts": {"acceptance": receipt, "render": render},
            "safe_to_retry_original": False,
            "status": "already_accepted",
            "validation": validation.to_dict(),
        }
    )
    return envelope


def _task_accept_authority_events(conn: sqlite3.Connection, task_id: str) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT id, sequence, payload_json
        FROM events
        WHERE event_type = 'task_status_changed'
          AND entity_type = 'task'
          AND entity_id = ?
        ORDER BY sequence
        """,
        (task_id,),
    ).fetchall()
    result: list[sqlite3.Row] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("task_acceptance"), dict):
            result.append(row)
    return result


def _verify_replay_ledger(
    paths: ProjectPaths,
    *,
    identity: dict[str, Any],
    evidence_id: str,
    authority_event_id: str,
    receipt_sha256: str,
    require_accepted: bool = True,
) -> _LedgerState:
    roots = _task_accept_roots(paths)
    locator_hex = str(identity["request_locator"]).removeprefix("sha256:")
    claim = _read_json_required(roots["claims"] / f"{locator_hex}.claim.json")
    if (
        claim.get("request_id") != identity["request_id"]
        or claim.get("request_locator") != identity["request_locator"]
        or claim.get("evidence_id") != evidence_id
        or claim.get("artifact") != identity["artifact"]
    ):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted request claim does not match its DB authority.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    reservations = list(
        roots["reservations"].glob(
            f"{evidence_id.lower()}--{locator_hex}.reservation.json"
        )
    )
    if len(reservations) != 1:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted request Evidence reservation is missing or ambiguous.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    reservation = _read_json_required(reservations[0])
    if (
        reservation.get("request_id") != identity["request_id"]
        or reservation.get("evidence_id") != evidence_id
    ):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted request Evidence reservation is corrupt.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    request_dir = roots["requests"] / locator_hex
    try:
        entries = sorted(request_dir.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted request generation ledger is missing.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        ) from exc
    previous_digest: str | None = None
    accepted_count = 0
    tail_recovery_generation = 0
    verified_generations: list[_Generation] = []
    for expected, directory in enumerate(entries):
        match = _GENERATION_DIR.fullmatch(directory.name)
        if match is None or int(match.group(1)) != expected or not directory.is_dir() or directory.is_symlink():
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The accepted request generation ledger is forked or incomplete.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        record_path = directory / "generation.json"
        record = _read_json_required(record_path)
        if (
            record.get("generation") != expected
            or record.get("request_id") != identity["request_id"]
            or record.get("request_locator") != identity["request_locator"]
            or record.get("evidence_id") != evidence_id
            or record.get("previous_generation_sha256") != previous_digest
        ):
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "The accepted request generation chain is corrupt.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
        previous_digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
        verified_generations.append(
            _Generation(
                number=expected,
                directory=directory,
                record=record,
                record_sha256=previous_digest,
                created=False,
            )
        )
        accepted_path = directory / "accepted.json"
        if accepted_path.exists():
            accepted = _read_json_required(accepted_path)
            if (
                accepted.get("request_id") != identity["request_id"]
                or accepted.get("authority_event_id") != authority_event_id
                or accepted.get("evidence_id") != evidence_id
                or accepted.get("receipt_sha256") != receipt_sha256
                or accepted.get("contract_version")
                != "task-accept-accepted-marker/v1"
                or accepted.get("state") != "accepted"
            ):
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "An accepted generation marker conflicts with DB authority.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            accepted_count += 1
        tail_entries = sorted(directory.glob("tail-recovery-*.json"))
        previous_tail_digest: str | None = None
        for tail_expected, tail_path in enumerate(tail_entries, start=1):
            if tail_path.name != f"tail-recovery-{tail_expected:04d}.json":
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "A Task Accept tail-recovery ledger is forked or incomplete.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            tail = _read_json_required(tail_path)
            if (
                tail.get("contract_version") != "task-accept-tail-recovery/v1"
                or tail.get("generation") != tail_expected
                or tail.get("request_id") != identity["request_id"]
                or tail.get("authority_event_id") != authority_event_id
                or tail.get("evidence_id") != evidence_id
                or tail.get("previous_tail_sha256") != previous_tail_digest
                or tail.get("state") != "planned"
                or tail.get("accepted_marker_sha256")
                != hashlib.sha256(
                    _canonical_bytes(
                        _accepted_marker_value(
                            request_id=str(identity["request_id"]),
                            authority_event_id=authority_event_id,
                            evidence_id=evidence_id,
                            receipt_sha256=receipt_sha256,
                        )
                    )
                    + b"\n"
                ).hexdigest()
            ):
                raise _Abort(
                    "task_accept_request_ledger_corrupt",
                    "A Task Accept tail-recovery ledger record is corrupt.",
                    EXIT_DATA_ERROR,
                    "replay_ledger",
                    False,
                    True,
                )
            previous_tail_digest = hashlib.sha256(tail_path.read_bytes()).hexdigest()
        tail_recovery_generation += len(tail_entries)
        unknown = {path.name for path in directory.iterdir()} - {
            "generation.json",
            "accepted.json",
            *(path.name for path in tail_entries),
        }
        if unknown:
            raise _Abort(
                "task_accept_request_ledger_corrupt",
                "An accepted generation contains unknown records.",
                EXIT_DATA_ERROR,
                "replay_ledger",
                False,
                True,
            )
    if not entries or accepted_count > 1 or (require_accepted and accepted_count != 1):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "The accepted request must have exactly one accepted generation leaf.",
            EXIT_DATA_ERROR,
            "replay_ledger",
            False,
            True,
        )
    return _LedgerState(
        generations=tuple(verified_generations),
        accepted_count=accepted_count,
        tail_recovery_generation=tail_recovery_generation,
    )


def recover_task_accept_tails(paths: ProjectPaths) -> dict[str, Any]:
    """Seal committed Task Accept authorities without replaying business state."""

    result = {
        "scanned": 0,
        "recovered": 0,
        "accepted_markers_published": 0,
        "tail_recovery_records_published": 0,
    }
    if not paths.db_path.is_file():
        return result
    with project_operation_lock(paths.loop_dir, exclusive=True):
        conn = connect(paths.db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, sequence, event_type, entity_type, entity_id,
                       payload_json, created_at
                FROM events
                WHERE event_type = 'task_status_changed'
                  AND entity_type = 'task'
                ORDER BY sequence
                """
            ).fetchall()
            for authority_row in rows:
                try:
                    payload = json.loads(str(authority_row["payload_json"]))
                except json.JSONDecodeError:
                    continue
                receipt = payload.get("task_acceptance") if isinstance(payload, dict) else None
                if not isinstance(receipt, dict):
                    continue
                result["scanned"] += 1
                request_id = receipt.get("request_id")
                request_locator = receipt.get("request_locator")
                evidence_id = receipt.get("base_evidence_id")
                if not all(isinstance(value, str) and value for value in (request_id, request_locator, evidence_id)):
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept receipt has incomplete request identity.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                locator_hex = request_locator.removeprefix("sha256:")
                claim = _read_json_required(
                    _task_accept_roots(paths)["claims"] / f"{locator_hex}.claim.json"
                )
                artifact = claim.get("artifact")
                if not isinstance(artifact, dict):
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept claim has no artifact identity.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                identity = {
                    "request_id": request_id,
                    "request_locator": request_locator,
                    "project_instance_id": receipt.get("project_instance_id"),
                    "task_id": receipt.get("task_id"),
                    "feature_id": receipt.get("feature_id"),
                    "test_ids": receipt.get("test_ids"),
                    "artifact": artifact,
                }
                _verify_current_proof_identity(
                    paths,
                    conn,
                    receipt=receipt,
                    identity=identity,
                    evidence_id=evidence_id,
                    authority_row=authority_row,
                )
                _require_current_acceptance_targets(
                    conn,
                    identity=identity,
                    evidence_id=evidence_id,
                    authority_sequence=int(authority_row["sequence"]),
                )
                ledger = _verify_replay_ledger(
                    paths,
                    identity=identity,
                    evidence_id=evidence_id,
                    authority_event_id=str(authority_row["id"]),
                    receipt_sha256=_sha256_canonical(receipt),
                    require_accepted=False,
                )
                if ledger.accepted_count == 1:
                    continue
                eligible = [
                    generation
                    for generation in ledger.generations
                    if generation.record.get("evidence_id") == evidence_id
                    and generation.record.get("pre_accept_prefix", {})
                    .get("hwm", {})
                    .get("sequence")
                    == receipt.get("pre_accept_prefix_hwm")
                    and generation.record.get("pre_accept_prefix", {}).get("sha256")
                    == receipt.get("pre_accept_prefix_sha256")
                ]
                if len(eligible) != 1:
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A committed Task Accept authority has no unique attempt generation.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                generation = eligible[0]
                existing_tail = sorted(generation.directory.glob("tail-recovery-*.json"))
                if existing_tail:
                    tail_path = existing_tail[-1]
                    tail_record = _read_json_required(tail_path)
                else:
                    tail_number = 1
                    tail_path = generation.directory / f"tail-recovery-{tail_number:04d}.json"
                    accepted_value = _accepted_marker_value(
                        request_id=request_id,
                        authority_event_id=str(authority_row["id"]),
                        evidence_id=evidence_id,
                        receipt_sha256=_sha256_canonical(receipt),
                    )
                    tail_record = {
                        "contract_version": "task-accept-tail-recovery/v1",
                        "generation": tail_number,
                        "request_id": request_id,
                        "authority_event_id": str(authority_row["id"]),
                        "evidence_id": evidence_id,
                        "previous_tail_sha256": None,
                        "accepted_marker_sha256": hashlib.sha256(
                            _canonical_bytes(accepted_value) + b"\n"
                        ).hexdigest(),
                        "state": "planned",
                    }
                    result["tail_recovery_records_published"] += int(
                        _publish_json_exclusive(tail_path, tail_record, allow_exact=False)
                    )
                accepted_value = _accepted_marker_value(
                    request_id=request_id,
                    authority_event_id=str(authority_row["id"]),
                    evidence_id=evidence_id,
                    receipt_sha256=_sha256_canonical(receipt),
                )
                if tail_record.get("accepted_marker_sha256") != hashlib.sha256(
                    _canonical_bytes(accepted_value) + b"\n"
                ).hexdigest():
                    raise _Abort(
                        "task_accept_request_ledger_corrupt",
                        "A Task Accept tail-recovery plan conflicts with DB authority.",
                        EXIT_DATA_ERROR,
                        "tail_recovery",
                    )
                result["accepted_markers_published"] += int(
                    _publish_json_exclusive(
                        generation.directory / "accepted.json",
                        accepted_value,
                        allow_exact=True,
                    )
                )
                result["recovered"] += 1
        finally:
            conn.close()
    return result


def _require_current_acceptance_targets(
    conn: sqlite3.Connection,
    *,
    identity: dict[str, Any],
    evidence_id: str,
    authority_sequence: int,
) -> None:
    expected_links = {
        ("task", str(identity["task_id"]), "supporting"),
        ("feature", str(identity["feature_id"]), "acceptance"),
        *{
            ("test_case", str(test_id), "acceptance")
            for test_id in identity["test_ids"]
        },
    }
    for target_type, target_id, role in expected_links:
        linked_ids = {
            str(row["evidence_id"])
            for row in conn.execute(
                """
                SELECT evidence_id FROM evidence_links
                WHERE target_type = ? AND target_id = ? AND link_role = ?
                """,
                (target_type, target_id, role),
            ).fetchall()
        }
        if linked_ids != {evidence_id}:
            raise _Abort(
                "task_accept_replay_not_current",
                "A Task acceptance target no longer has one current base Evidence.",
                1,
                "current_proof",
                False,
                True,
            )
    related_ids = {
        str(identity["task_id"]),
        str(identity["feature_id"]),
        evidence_id,
        *(str(test_id) for test_id in identity["test_ids"]),
    }
    later_related = conn.execute(
        f"""
        SELECT id FROM events
        WHERE sequence > ?
          AND entity_id IN ({','.join('?' for _ in related_ids)})
        ORDER BY sequence LIMIT 1
        """,
        (authority_sequence, *sorted(related_ids)),
    ).fetchone()
    if later_related is not None:
        raise _Abort(
            "task_accept_replay_not_current",
            "A related acceptance entity changed after its Task authority.",
            1,
            "current_proof",
            False,
            True,
        )


def _verified_common_prefix(paths: ProjectPaths, conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events ORDER BY sequence
        """
    ).fetchall()
    expected = b"".join(canonical_event_bytes(canonical_event_record(row)) for row in rows)
    try:
        actual = paths.events_path.read_bytes()
    except OSError as exc:
        raise _Abort(
            "task_accept_json_integrity_invalid",
            "events.jsonl could not be read.",
            EXIT_DATA_ERROR,
            "prefix",
        ) from exc
    if actual != expected:
        raise _Abort(
            "task_accept_json_integrity_invalid",
            "SQLite events and events.jsonl do not share an exact canonical prefix.",
            EXIT_DATA_ERROR,
            "prefix",
        )
    last = rows[-1] if rows else None
    return {
        "hwm": {
            "sequence": 0 if last is None else int(last["sequence"]),
            "event_id": None if last is None else str(last["id"]),
        },
        "sha256": hashlib.sha256(expected).hexdigest(),
    }


def _project_instance_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
        FROM events WHERE event_type = 'project_initialized'
        ORDER BY sequence LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise _Abort(
            "task_accept_project_instance_missing",
            "Project initialization authority is missing.",
            EXIT_DATA_ERROR,
            "identity",
        )
    return hashlib.sha256(canonical_event_bytes(canonical_event_record(row))).hexdigest()


def _require_delivered_outbox(conn: sqlite3.Connection) -> None:
    count = int(
        conn.execute("SELECT COUNT(*) FROM outbox_records WHERE status != 'delivered'").fetchone()[0]
    )
    if count:
        raise _Abort(
            "task_accept_projection_pending",
            "A pre-existing JSONL projection is pending.",
            EXIT_RECOVERABLE_PENDING,
            "admission",
            True,
            False,
            "pcl audit flush --json",
        )


def _verify_final_rows_and_events(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    feature_id: str,
    test_ids: list[str],
    evidence_id: str,
    event_plan: list[dict[str, Any]],
) -> None:
    task = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    feature = conn.execute("SELECT status FROM features WHERE id = ?", (feature_id,)).fetchone()
    tests = conn.execute(
        f"SELECT id, status, evidence_id FROM test_cases WHERE id IN ({','.join('?' for _ in test_ids)}) ORDER BY id",
        tuple(test_ids),
    ).fetchall()
    planned_rows = conn.execute(
        f"SELECT id, sequence FROM events WHERE id IN ({','.join('?' for _ in event_plan)}) ORDER BY sequence",
        tuple(str(item["event_id"]) for item in event_plan),
    ).fetchall()
    if (
        task is None
        or task["status"] != "done"
        or feature is None
        or feature["status"] != "done"
        or len(tests) != len(test_ids)
        or any(row["status"] != "passing" or row["evidence_id"] != evidence_id for row in tests)
        or [(str(row["id"]), int(row["sequence"])) for row in planned_rows]
        != [(str(item["event_id"]), int(item["sequence"])) for item in event_plan]
    ):
        raise _Abort(
            "task_accept_post_strict_contract_violation",
            "The sealed final Task acceptance snapshot does not match the plan.",
            EXIT_DATA_ERROR,
            "seal",
        )


def _run_postcommit_render(
    paths: ProjectPaths,
    *,
    operation_capability: object,
    authority_event_id: str,
) -> dict[str, Any]:
    try:
        if not dashboard_auto_render(paths.root):
            return {"status": "disabled", "authority_event_id": authority_event_id}
        _render_dashboard_with_lock(paths, capability=operation_capability)
        return {
            "status": "rendered",
            "authority_event_id": authority_event_id,
            "dashboard_data_sha256": hashlib.sha256(paths.dashboard_data.read_bytes()).hexdigest(),
            "dashboard_html_sha256": hashlib.sha256(paths.dashboard_html.read_bytes()).hexdigest(),
        }
    except Exception:
        return {"status": "pending", "authority_event_id": authority_event_id}


def _verify_replay_render(paths: ProjectPaths, *, identity: dict[str, Any]) -> dict[str, Any]:
    if not dashboard_auto_render(paths.root):
        return {"status": "disabled"}
    try:
        data = json.loads(paths.dashboard_data.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "pending"}
    if not isinstance(data, dict):
        return {"status": "pending"}
    tasks = {
        str(row.get("id")): row
        for row in data.get("tasks", [])
        if isinstance(row, dict)
    }
    features = {
        str(row.get("id")): row
        for row in data.get("features", [])
        if isinstance(row, dict)
    }
    tests = {
        str(row.get("id")): row
        for row in data.get("test_cases", [])
        if isinstance(row, dict)
    }
    if (
        tasks.get(str(identity["task_id"]), {}).get("status") == "done"
        and features.get(str(identity["feature_id"]), {}).get("status") == "done"
        and all(
            tests.get(str(test_id), {}).get("status") == "passing"
            for test_id in identity["test_ids"]
        )
    ):
        return {
            "status": "verified",
            "dashboard_data_sha256": hashlib.sha256(paths.dashboard_data.read_bytes()).hexdigest(),
        }
    return {"status": "pending"}


def _publish_accepted_marker(
    generation: _Generation,
    *,
    request_id: str,
    authority_event_id: str,
    evidence_id: str,
    receipt_sha256: str,
) -> bool:
    return _publish_json_exclusive(
        generation.directory / "accepted.json",
        _accepted_marker_value(
            request_id=request_id,
            authority_event_id=authority_event_id,
            evidence_id=evidence_id,
            receipt_sha256=receipt_sha256,
        ),
        allow_exact=True,
    )


def _accepted_marker_value(
    *,
    request_id: str,
    authority_event_id: str,
    evidence_id: str,
    receipt_sha256: str,
) -> dict[str, Any]:
    return {
        "contract_version": "task-accept-accepted-marker/v1",
        "request_id": request_id,
        "authority_event_id": authority_event_id,
        "evidence_id": evidence_id,
        "receipt_sha256": receipt_sha256,
        "state": "accepted",
    }


def _verify_artifact_again(paths: ProjectPaths, artifact: _Artifact) -> None:
    content, binding = secure_read_project_artifact(
        paths,
        artifact.relative_path,
        max_bytes=TASK_ACCEPT_MAX_ARTIFACT_BYTES,
    )
    try:
        if content != artifact.content or hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise _Abort(
                "task_accept_artifact_hash_drift",
                "The acceptance artifact changed during the request.",
                1,
                "artifact_revalidation",
            )
    finally:
        binding.close()


def _task_accept_roots(paths: ProjectPaths) -> dict[str, Path]:
    return {
        "reservations": paths.evidence_dir / "task-accept-reservations",
        "claims": paths.evidence_dir / "task-accept-claims",
        "requests": paths.evidence_dir / "task-accept-requests",
    }


def _ensure_directory(path: Path) -> None:
    if path.exists():
        _require_real_directory(path)
        return
    parent = path.parent
    if not parent.exists():
        _ensure_directory(parent)
    _require_real_directory(parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        _require_real_directory(path)


def _require_real_directory(path: Path) -> None:
    try:
        value = os.lstat(path)
    except OSError as exc:
        raise _Abort(
            "task_accept_artifact_publish_failed",
            "A durable Task Accept directory cannot be inspected.",
            EXIT_DATA_ERROR,
            "publish",
        ) from exc
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        raise _Abort(
            "task_accept_artifact_publish_failed",
            "A durable Task Accept path is not a real directory.",
            EXIT_DATA_ERROR,
            "publish",
        )


def _publish_json_exclusive(path: Path, value: dict[str, Any], *, allow_exact: bool) -> bool:
    return _publish_bytes_exclusive(
        path,
        _canonical_bytes(value) + b"\n",
        allow_exact=allow_exact,
    )


def _publish_bytes_exclusive(path: Path, content: bytes, *, allow_exact: bool) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if not allow_exact:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "A durable Task Accept artifact already exists.",
                EXIT_DATA_ERROR,
                "publish",
            )
        try:
            current = path.read_bytes()
            metadata = os.lstat(path)
        except OSError as exc:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "An existing durable Task Accept artifact cannot be verified.",
                EXIT_DATA_ERROR,
                "publish",
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or current != content:
            raise _Abort(
                "task_accept_artifact_publish_failed",
                "An existing durable Task Accept artifact is ambiguous.",
                EXIT_DATA_ERROR,
                "publish",
            )
        return False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != content:
            raise OSError("exclusive publish verification failed")
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except Exception as exc:
        raise _Abort(
            "task_accept_artifact_publish_failed",
            "A durable Task Accept artifact could not be published.",
            EXIT_DATA_ERROR,
            "publish",
        ) from exc


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json_required(path)


def _read_json_required(path: Path) -> dict[str, Any]:
    try:
        metadata = os.lstat(path)
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept ledger record is unreadable.",
            EXIT_DATA_ERROR,
            "ledger",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or not isinstance(value, dict):
        raise _Abort(
            "task_accept_request_ledger_corrupt",
            "A durable Task Accept ledger record is invalid.",
            EXIT_DATA_ERROR,
            "ledger",
        )
    return value


def _framed_sha256(domain: str, value: dict[str, Any]) -> str:
    domain_bytes = domain.encode("utf-8")
    payload = _canonical_bytes(value)
    framed = (
        b"PCLF1"
        + len(domain_bytes).to_bytes(2, "big")
        + domain_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return hashlib.sha256(framed).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_canonical(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _prefixed_id_sort_key(value: str) -> tuple[int, str]:
    return decimal_sort_key(value.rsplit("-", 1)[1])


def _envelope() -> dict[str, Any]:
    return {
        "authority": None,
        "business_attempt_generation": 0,
        "business_changed": False,
        "changed": False,
        "effects": {
            "business_rows_changed": 0,
            "copies_published": 0,
            "events_appended": 0,
            "markers_published": 0,
            "outbox_appended": 0,
            "projection_writes": 0,
            "render_writes": 0,
        },
        "error_code": None,
        "exit_code": 0,
        "identity": None,
        "message": "",
        "mode": "preflight",
        "mutation_committed": False,
        "ok": False,
        "operation": "task_accept",
        "pending_tail": None,
        "phase": "input",
        "prior_acceptance_verified": False,
        "prior_authoritative_commit": False,
        "receipts": {},
        "safe_retry_action": None,
        "safe_to_retry_original": False,
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "tail_recovery_changed": False,
        "tail_recovery_generation": 0,
        "teardown": {"status": "not_started", "error": None},
        "validation": None,
    }


def _error_envelope(
    envelope: dict[str, Any],
    *,
    code: str,
    message: str,
    exit_code: int,
    phase: str,
    safe_to_retry_original: bool,
    prior_acceptance_verified: bool = False,
    safe_retry_action: str | None = None,
) -> dict[str, Any]:
    envelope.update(
        {
            "error_code": code,
            "exit_code": exit_code,
            "message": message,
            "mutation_committed": False,
            "ok": False,
            "phase": phase,
            "prior_acceptance_verified": prior_acceptance_verified,
            "safe_retry_action": safe_retry_action,
            "safe_to_retry_original": safe_to_retry_original,
            "status": "failed",
            "teardown": {"status": "complete", "error": None},
        }
    )
    return envelope


def _postcommit_error(
    envelope: dict[str, Any],
    *,
    code: str,
    message: str,
    identity: dict[str, Any],
    authority_event_id: str | None,
    evidence_id: str | None,
    generation: int,
    action: str,
    business_changed: bool,
    mutation_committed: bool,
    prior_authoritative_commit: bool,
) -> dict[str, Any]:
    envelope.update(
        {
            "authority": None
            if authority_event_id is None
            else {"event_id": authority_event_id, "evidence_id": evidence_id},
            "business_attempt_generation": generation,
            "business_changed": business_changed,
            "changed": business_changed,
            "error_code": code,
            "exit_code": EXIT_RECOVERABLE_PENDING,
            "identity": identity,
            "message": message,
            "mutation_committed": mutation_committed,
            "ok": False,
            "pending_tail": {"recovery_command": action},
            "phase": "postcommit_tail",
            "prior_acceptance_verified": prior_authoritative_commit,
            "prior_authoritative_commit": prior_authoritative_commit,
            "safe_retry_action": action,
            "safe_to_retry_original": False,
            "status": "pending_tail",
        }
    )
    return envelope


def _commit_outcome_unknown(
    envelope: dict[str, Any],
    *,
    identity: dict[str, Any],
    authority_event_id: str,
    evidence_id: str,
    generation: int,
) -> dict[str, Any]:
    """Report a commit-boundary failure without guessing the durable outcome."""

    action = "pcl audit check --json"
    envelope.update(
        {
            "authority": {
                "event_id": authority_event_id,
                "evidence_id": evidence_id,
            },
            "business_attempt_generation": generation,
            "business_changed": False,
            "changed": False,
            "error_code": "task_accept_commit_outcome_unknown",
            "exit_code": EXIT_RECOVERABLE_PENDING,
            "identity": identity,
            "message": (
                "The SQLite commit outcome is unknown; do not retry the original "
                "Task acceptance request."
            ),
            "mutation_committed": None,
            "ok": False,
            "pending_tail": {"recovery_command": action},
            "phase": "sqlite_commit",
            "prior_acceptance_verified": False,
            "prior_authoritative_commit": False,
            "safe_retry_action": action,
            "safe_to_retry_original": False,
            "status": "outcome_unknown",
            "teardown": {"status": "complete", "error": None},
        }
    )
    return envelope
