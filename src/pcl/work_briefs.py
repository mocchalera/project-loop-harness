from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .approval_provenance import (
    approval_provenance,
    provenance_from_event_payload,
    resolve_actor_kind,
    resolve_recording_provenance,
)
from .contracts.work_brief import (
    load_work_brief,
    serialized_work_brief,
    validate_work_brief,
    work_brief_sha256,
)
from .db import connect, connect_mutation, table_exists
from .errors import DataStoreError, InvalidInputError, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


WORK_BRIEF_EVIDENCE_TYPE = "work_brief"
WORK_BRIEF_LINK_ROLE = "work_brief"

_TARGET_TABLES = {
    "goal": "goals",
    "task": "tasks",
    "feature": "features",
    "story": "user_stories",
    "defect": "defects",
    "workflow_run": "workflow_runs",
}


class WorkBriefError(PclError):
    pass


def add_work_brief(
    paths: ProjectPaths,
    *,
    file: str,
    summary: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    summary = _required(summary, "summary")
    brief = _load_valid_brief(file)
    target = _brief_target(brief)
    artifact_sha256 = work_brief_sha256(brief)
    _preflight_target_and_duplicate(paths, brief)

    planned = {
        "brief_id": brief["brief_id"],
        "revision": brief["revision"],
        "target": target,
        "artifact_sha256": artifact_sha256,
    }
    if dry_run:
        return {"ok": True, "changed": False, "dry_run": True, "planned": planned}

    conn = connect_mutation(paths)
    final_path: Path | None = None
    temp_path: Path | None = None
    try:
        _validate_target_and_duplicate(conn, paths, brief)
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        artifact_dir = paths.evidence_dir / "work-briefs"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        final_path = artifact_dir / f"{evidence_id.lower()}-work-brief-v1.json"
        temp_path = final_path.with_suffix(".json.tmp")
        temp_path.write_text(serialized_work_brief(brief), encoding="utf-8")
        temp_path.replace(final_path)
        now = utc_now_iso()
        relative_path = final_path.relative_to(paths.root).as_posix()
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (evidence_id, WORK_BRIEF_EVIDENCE_TYPE, relative_path, summary, now),
        )
        conn.execute(
            """
            INSERT INTO evidence_links(
              evidence_id, target_type, target_id, link_role, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                target["type"],
                target["id"],
                WORK_BRIEF_LINK_ROLE,
                now,
            ),
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="work_brief_recorded",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                **planned,
                "evidence_id": evidence_id,
                "path": relative_path,
                "summary": summary,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "dry_run": False,
            "event_id": event_id,
            "evidence": {
                "id": evidence_id,
                "type": WORK_BRIEF_EVIDENCE_TYPE,
                "path": relative_path,
                "summary": summary,
                **planned,
            },
        }
    except PclError:
        conn.rollback()
        _remove_uncommitted_file(conn, temp_path, final_path)
        raise
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        _remove_uncommitted_file(conn, temp_path, final_path)
        raise DataStoreError(
            f"Could not record Work Brief Evidence: {exc}",
            details={"file": file},
        ) from exc
    finally:
        conn.close()


def approve_work_brief(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    actor: str,
    actor_kind: str | None = None,
    recorded_by: str | None = None,
    recorder_kind: str | None = None,
    source_kind: str | None = None,
    source_ref: str | None = None,
    reason: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    actor = _required(actor, "actor")
    reason = _required(reason, "reason")
    resolved_actor_kind = resolve_actor_kind(actor=actor, actor_kind=actor_kind)
    if resolved_actor_kind != "human":
        raise _error(
            "work_brief_human_approval_required",
            "Work Brief approval requires human-origin provenance; record a review instead.",
            actor=actor,
            actor_kind=resolved_actor_kind,
            suggested_command=(
                f"pcl brief review {evidence_id} --actor '{actor}' "
                f"--actor-kind {resolved_actor_kind} --reason '<review outcome>'"
            ),
        )
    recording = resolve_recording_provenance(
        actor=actor,
        actor_kind=resolved_actor_kind,
        recorded_by=recorded_by,
        recorder_kind=recorder_kind,
        source_kind=source_kind,
        source_ref=source_ref,
        command="pcl brief approve",
    )
    preview = show_work_brief(paths, evidence_id=evidence_id)
    if preview["work_brief"]["health"] != "ok":
        raise _error(
            "work_brief_unhealthy",
            f"Work Brief Evidence {evidence_id} is not healthy enough for approval.",
            evidence_id=evidence_id,
            findings=preview["work_brief"]["findings"],
        )
    now = utc_now_iso()
    receipt = approval_provenance(
        action="approval",
        actor_kind=resolved_actor_kind,
        actor=actor,
        source=recording["source"],
        source_kind=recording["source_kind"],
        source_ref=recording["source_ref"],
        recorder_kind=recording["recorder_kind"],
        recorder=recording["recorder"],
        timestamp=now,
        target=preview["work_brief"]["target"],
        evidence_id=evidence_id,
        artifact_sha256=preview["work_brief"]["artifact_sha256"],
        reason=reason,
    )
    planned = {
        "evidence_id": evidence_id,
        "target": preview["work_brief"]["target"],
        "artifact_sha256": preview["work_brief"]["artifact_sha256"],
        "actor": actor,
        "actor_kind": resolved_actor_kind,
        "recorder": recording["recorder"],
        "recorder_kind": recording["recorder_kind"],
        "source": recording["source"],
        "source_kind": recording["source_kind"],
        "source_ref": recording["source_ref"],
        "reason": reason,
        "approval_provenance": receipt,
    }
    if dry_run:
        return {"ok": True, "changed": False, "dry_run": True, "planned": planned}

    conn = connect_mutation(paths)
    try:
        current = _show_work_brief(conn, paths, evidence_id)
        if current["health"] != "ok":
            raise _error(
                "work_brief_unhealthy",
                f"Work Brief Evidence {evidence_id} changed before approval.",
                evidence_id=evidence_id,
                findings=current["findings"],
            )
        target = current["target"]
        approvals = [
            item for item in _approval_events(conn, target) if item.get("actor_kind") == "human"
        ]
        matching = [
            item
            for item in approvals
            if item["evidence_id"] == evidence_id
            and item["artifact_sha256"] == current["artifact_sha256"]
        ]
        conflicting = [item for item in approvals if item not in matching]
        if conflicting:
            raise _error(
                "work_brief_approval_conflict",
                f"Target {target['type']}:{target['id']} already has another approved Work Brief.",
                target=target,
                approved_evidence_ids=sorted({item["evidence_id"] for item in conflicting}),
            )
        if matching:
            conn.rollback()
            return {
                "ok": True,
                "changed": False,
                "dry_run": False,
                "event_id": matching[-1]["event_id"],
                "approval": matching[-1],
            }
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="work_brief_approved",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "evidence_id": evidence_id,
                "brief_id": current["brief_id"],
                "revision": current["revision"],
                "target": target,
                "artifact_sha256": current["artifact_sha256"],
                "actor": actor,
                "reason": reason,
                "actor_kind": resolved_actor_kind,
                "recorder": recording["recorder"],
                "recorder_kind": recording["recorder_kind"],
                "source": recording["source"],
                "source_kind": recording["source_kind"],
                "source_ref": recording["source_ref"],
                "approval_provenance": receipt,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "dry_run": False,
            "event_id": event_id,
            "approval": {**planned, "event_id": event_id},
        }
    except PclError:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise DataStoreError(
            f"Could not approve Work Brief Evidence: {exc}",
            details={"evidence_id": evidence_id},
        ) from exc
    finally:
        conn.close()


def review_work_brief(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    actor: str,
    actor_kind: str | None,
    reason: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    actor = _required(actor, "actor")
    reason = _required(reason, "reason")
    resolved_actor_kind = resolve_actor_kind(actor=actor, actor_kind=actor_kind)
    preview = show_work_brief(paths, evidence_id=evidence_id)["work_brief"]
    if preview["health"] != "ok":
        raise _error(
            "work_brief_unhealthy",
            f"Work Brief Evidence {evidence_id} is not healthy enough for review.",
            evidence_id=evidence_id,
            findings=preview["findings"],
        )
    now = utc_now_iso()
    receipt = approval_provenance(
        action="review",
        actor_kind=resolved_actor_kind,
        actor=actor,
        source="pcl brief review",
        timestamp=now,
        target=preview["target"],
        evidence_id=evidence_id,
        artifact_sha256=preview["artifact_sha256"],
        reason=reason,
    )
    if dry_run:
        return {"ok": True, "changed": False, "dry_run": True, "planned": receipt}

    conn = connect_mutation(paths)
    try:
        current = _show_work_brief(conn, paths, evidence_id)
        if current["health"] != "ok" or current["artifact_sha256"] != receipt["bound_evidence"]["artifact_sha256"]:
            raise _error(
                "work_brief_unhealthy",
                f"Work Brief Evidence {evidence_id} changed before review.",
                evidence_id=evidence_id,
                findings=current["findings"],
            )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="work_brief_reviewed",
            entity_type="evidence",
            entity_id=evidence_id,
            payload={
                "evidence_id": evidence_id,
                "target": current["target"],
                "artifact_sha256": current["artifact_sha256"],
                "actor": actor,
                "actor_kind": resolved_actor_kind,
                "reason": reason,
                "source": "pcl brief review",
                "approval_provenance": receipt,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "changed": True,
            "dry_run": False,
            "event_id": event_id,
            "review": {**receipt, "event_id": event_id, "created_at": now},
        }
    except PclError:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise DataStoreError(
            f"Could not review Work Brief Evidence: {exc}",
            details={"evidence_id": evidence_id},
        ) from exc
    finally:
        conn.close()


def show_work_brief(
    paths: ProjectPaths,
    *,
    evidence_id: str | None = None,
    target_ref: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    if (evidence_id is None) == (target_ref is None):
        raise InvalidInputError(
            "Exactly one of evidence_id or target_ref is required.",
            details={"evidence_id": evidence_id, "target_ref": target_ref},
        )
    conn = connect(paths.db_path)
    try:
        if evidence_id is not None:
            return {"ok": True, "work_brief": _show_work_brief(conn, paths, evidence_id)}
        target = parse_target_ref(str(target_ref))
        _validate_target(conn, target)
        rows = conn.execute(
            """
            SELECT evidence_id
            FROM evidence_links
            WHERE target_type = ? AND target_id = ? AND link_role = ?
            ORDER BY created_at, evidence_id
            """,
            (target["type"], target["id"], WORK_BRIEF_LINK_ROLE),
        ).fetchall()
        briefs = [_show_work_brief(conn, paths, str(row["evidence_id"])) for row in rows]
        approved = [item for item in briefs if item["approved"] and item["health"] == "ok"]
        if len(approved) > 1:
            raise _error(
                "work_brief_approval_ambiguous",
                f"Target {target['type']}:{target['id']} has multiple approved Work Briefs.",
                target=target,
                evidence_ids=[item["evidence_id"] for item in approved],
            )
        return {
            "ok": True,
            "target": target,
            "current": approved[0] if approved else None,
            "candidates": briefs,
        }
    finally:
        conn.close()


def current_approved_work_brief(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any] | None:
    if not table_exists(conn, "evidence_links"):
        return None
    target = {"type": target_type, "id": target_id}
    rows = conn.execute(
        """
        SELECT evidence_id
        FROM evidence_links
        WHERE target_type = ? AND target_id = ? AND link_role = ?
        ORDER BY created_at, evidence_id
        """,
        (target_type, target_id, WORK_BRIEF_LINK_ROLE),
    ).fetchall()
    approved = []
    for row in rows:
        item = _show_work_brief(conn, paths, str(row["evidence_id"]))
        if item["approved"] and item["health"] == "ok":
            approved.append(item)
    if len(approved) > 1:
        raise _error(
            "work_brief_approval_ambiguous",
            f"Target {target_type}:{target_id} has multiple approved Work Briefs.",
            target=target,
            evidence_ids=[item["evidence_id"] for item in approved],
        )
    return approved[0] if approved else None


def parse_target_ref(value: str) -> dict[str, str]:
    target_type, separator, target_id = str(value or "").partition(":")
    if not separator or not target_type or not target_id:
        raise InvalidInputError(
            "Target must be formatted as <target-type>:<target-id>.",
            details={"target": value},
        )
    return {"type": target_type, "id": target_id}


def _load_valid_brief(file: str) -> dict[str, Any]:
    try:
        value = load_work_brief(file)
    except OSError as exc:
        raise InvalidInputError(
            f"Could not read Work Brief file: {file}",
            details={"file": file, "reason": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise InvalidInputError(
            f"Work Brief file is not valid JSON: {file}",
            details={"file": file, "line": exc.lineno, "column": exc.colno},
        ) from exc
    except ValueError as exc:
        raise InvalidInputError(
            f"Work Brief file contains an invalid JSON value: {file}",
            details={"file": file, "reason": str(exc)},
        ) from exc
    result = validate_work_brief(value)
    if not result.ok:
        raise _error(
            "work_brief_contract_invalid",
            f"Work Brief contract validation failed: {file}",
            file=file,
            errors=list(result.errors),
        )
    return value


def _brief_target(brief: dict[str, Any]) -> dict[str, str]:
    target = brief["target"]
    return {"type": str(target["type"]), "id": str(target["id"])}


def _preflight_target_and_duplicate(paths: ProjectPaths, brief: dict[str, Any]) -> None:
    conn = connect(paths.db_path)
    try:
        _validate_target_and_duplicate(conn, paths, brief)
    finally:
        conn.close()


def _validate_target_and_duplicate(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    brief: dict[str, Any],
) -> None:
    if not table_exists(conn, "evidence_links"):
        raise _error(
            "work_brief_evidence_links_required",
            "Work Brief requires schema 7 evidence_links support.",
        )
    target = _brief_target(brief)
    _validate_target(conn, target)
    rows = conn.execute(
        "SELECT id, path FROM evidence WHERE type = ? ORDER BY created_at, id",
        (WORK_BRIEF_EVIDENCE_TYPE,),
    ).fetchall()
    for row in rows:
        try:
            existing = load_work_brief(paths.root / str(row["path"]))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(existing, dict)
            and existing.get("brief_id") == brief["brief_id"]
            and existing.get("revision") == brief["revision"]
        ):
            raise _error(
                "work_brief_duplicate_revision",
                f"Work Brief {brief['brief_id']} revision {brief['revision']} already exists.",
                brief_id=brief["brief_id"],
                revision=brief["revision"],
                evidence_id=str(row["id"]),
            )


def _validate_target(conn: sqlite3.Connection, target: dict[str, str]) -> None:
    table = _TARGET_TABLES.get(target["type"])
    if table is None:
        raise _error(
            "work_brief_unknown_target_type",
            f"Unsupported Work Brief target type: {target['type']}",
            target=target,
        )
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target["id"],)).fetchone() is None:
        raise _error(
            "work_brief_unknown_target",
            f"Work Brief target does not exist: {target['type']}:{target['id']}",
            target=target,
        )


def _show_work_brief(
    conn: sqlite3.Connection,
    paths: ProjectPaths,
    evidence_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, type, path, summary, created_at FROM evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None or row["type"] != WORK_BRIEF_EVIDENCE_TYPE:
        raise _error(
            "work_brief_unknown_evidence",
            f"Work Brief Evidence does not exist: {evidence_id}",
            evidence_id=evidence_id,
        )
    links = conn.execute(
        """
        SELECT target_type, target_id
        FROM evidence_links
        WHERE evidence_id = ? AND link_role = ?
        ORDER BY target_type, target_id
        """,
        (evidence_id, WORK_BRIEF_LINK_ROLE),
    ).fetchall()
    findings: list[dict[str, Any]] = []
    if len(links) != 1:
        findings.append({"code": "target_link_count", "actual": len(links), "expected": 1})
        target = {"type": "", "id": ""}
    else:
        target = {"type": str(links[0]["target_type"]), "id": str(links[0]["target_id"])}
    path = paths.root / str(row["path"])
    brief: dict[str, Any] | None = None
    try:
        value = load_work_brief(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append({"code": "artifact_unreadable", "reason": str(exc)})
    else:
        validation = validate_work_brief(value)
        if not validation.ok:
            findings.append({"code": "contract_invalid", "errors": list(validation.errors)})
        elif isinstance(value, dict):
            brief = value
            if _brief_target(value) != target:
                findings.append(
                    {"code": "target_mismatch", "artifact": _brief_target(value), "link": target}
                )
    artifact_sha256 = work_brief_sha256(brief) if brief is not None else None
    approvals = _approval_events(conn, target) if target["type"] else []
    reviews = _review_events(conn, target) if target["type"] else []
    own_approvals = [item for item in approvals if item["evidence_id"] == evidence_id]
    own_reviews = [item for item in reviews if item["bound_evidence"]["id"] == evidence_id]
    human_approvals = [item for item in own_approvals if item.get("actor_kind") == "human"]
    non_human_approvals = [item for item in own_approvals if item.get("actor_kind") != "human"]
    approval = human_approvals[-1] if human_approvals else None
    if non_human_approvals:
        findings.append(
            {
                "code": "approval_non_human",
                "event_ids": [item["event_id"] for item in non_human_approvals],
            }
        )
    if approval and approval["artifact_sha256"] != artifact_sha256:
        findings.append(
            {
                "code": "approval_hash_mismatch",
                "expected": approval["artifact_sha256"],
                "actual": artifact_sha256,
            }
        )
    return {
        "evidence_id": evidence_id,
        "brief_id": None if brief is None else brief["brief_id"],
        "revision": None if brief is None else brief["revision"],
        "target": target,
        "path": str(row["path"]),
        "summary": str(row["summary"]),
        "artifact_sha256": artifact_sha256,
        "approved": approval is not None and not findings,
        "approval": approval,
        "reviews": own_reviews,
        "health": "ok" if not findings else "warning",
        "findings": findings,
    }


def _approval_events(
    conn: sqlite3.Connection,
    target: dict[str, str],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, payload_json, created_at
        FROM events
        WHERE event_type = 'work_brief_approved'
        ORDER BY sequence, id
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("target") != target:
            continue
        receipt = provenance_from_event_payload(
            event_id=str(row["id"]),
            created_at=str(row["created_at"]),
            payload=payload,
            default_action="approval",
        )
        if receipt is None:
            continue
        result.append(
            {
                **receipt,
                "evidence_id": str(receipt["bound_evidence"]["id"]),
                "artifact_sha256": str(receipt["bound_evidence"]["artifact_sha256"]),
            }
        )
    return result


def _review_events(
    conn: sqlite3.Connection,
    target: dict[str, str],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, payload_json, created_at
        FROM events
        WHERE event_type = 'work_brief_reviewed'
        ORDER BY sequence, id
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("target") != target:
            continue
        receipt = provenance_from_event_payload(
            event_id=str(row["id"]),
            created_at=str(row["created_at"]),
            payload=payload,
            default_action="review",
        )
        if receipt is not None:
            result.append(receipt)
    return result


def _required(value: str, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise InvalidInputError(
            f"--{field.replace('_', '-')} must not be empty.",
            details={"field": field},
        )
    return cleaned


def _remove_uncommitted_file(
    conn: sqlite3.Connection,
    temp_path: Path | None,
    final_path: Path | None,
) -> None:
    if getattr(conn, "_authoritative_commit_completed", False):
        return
    for path in (temp_path, final_path):
        if path is not None and path.exists():
            path.unlink()


def _error(code: str, message: str, **details: Any) -> WorkBriefError:
    return WorkBriefError(message=message, code=code, details=details)
