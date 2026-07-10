from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .contracts.completion_packet import load_completion_packet, validate_completion_packet
from .db import connect, connect_mutation
from .errors import InvalidInputError
from .events import append_event
from .evidence import ADHOC_EVIDENCE_TYPES, EvidenceAddError, require_healthy_terminal_evidence
from .guards import require_initialized
from .paths import ProjectPaths
from .timeutil import utc_now_iso


TARGET_TABLES = {
    "goal": "goals",
    "feature": "features",
    "test_case": "test_cases",
    "task": "tasks",
    "agent_job": "agent_jobs",
}
ROLE_TARGETS = {
    "acceptance": {"test_case", "feature"},
    "completion_packet": {"goal", "feature", "task"},
    "supporting": set(TARGET_TABLES),
}
EXCLUSIVE_TARGET_BOUND_ROLES = {"acceptance", "completion_packet"}
RESERVED_LINK_ROLES = {
    "verification_check": "pcl finish",
    "code_context": "pcl impact --diff --for-task/--for-job",
}


class RelationshipRepairError(EvidenceAddError):
    pass


def repair_test_links(
    paths: ProjectPaths,
    *,
    test_case_id: str,
    story_id: str | None,
    evidence_id: str | None,
    summary: str,
) -> dict[str, Any]:
    require_initialized(paths)
    story_id = _clean_optional(story_id)
    evidence_id = _clean_optional(evidence_id)
    summary = _require_summary(summary)
    if story_id is None and evidence_id is None:
        raise InvalidInputError(
            "pcl test link requires at least one of --story or --evidence-id.",
            details={"test_case_id": test_case_id},
        )
    _preflight_test(paths, test_case_id, story_id, evidence_id)
    conn = connect_mutation(paths)
    try:
        test = _validate_test_links(paths, conn, test_case_id, story_id, evidence_id)
        before = {"story_id": test["story_id"], "evidence_id": test["evidence_id"]}
        after = {
            "story_id": story_id if story_id is not None else test["story_id"],
            "evidence_id": evidence_id if evidence_id is not None else test["evidence_id"],
        }
        link_exists = evidence_id is None or _link_exists(
            conn, evidence_id, "test_case", test_case_id, "acceptance"
        )
        if before == after and link_exists:
            conn.rollback()
            return {"ok": True, "changed": False, "id": test_case_id, "before": before, "after": after, "event_id": None}
        if evidence_id is not None and not link_exists:
            _insert_link(conn, evidence_id, "test_case", test_case_id, "acceptance")
        conn.execute(
            "UPDATE test_cases SET story_id = ?, evidence_id = ? WHERE id = ?",
            (after["story_id"], after["evidence_id"], test_case_id),
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="test_links_repaired",
            entity_type="test_case",
            entity_id=test_case_id,
            payload={"before": before, "after": after, "summary": summary},
        )
        conn.commit()
        return {"ok": True, "changed": True, "id": test_case_id, "before": before, "after": after, "event_id": event_id}
    finally:
        conn.close()


def add_evidence_link(
    paths: ProjectPaths,
    *,
    evidence_id: str,
    target_type: str,
    target_id: str,
    role: str,
    summary: str,
) -> dict[str, Any]:
    require_initialized(paths)
    summary = _require_summary(summary)
    _preflight_evidence_link(paths, evidence_id, target_type, target_id, role)
    conn = connect_mutation(paths)
    try:
        _validate_evidence_link(paths, conn, evidence_id, target_type, target_id, role)
        if _link_exists(conn, evidence_id, target_type, target_id, role):
            conn.rollback()
            return {"ok": True, "changed": False, "evidence_id": evidence_id, "target": {"type": target_type, "id": target_id}, "role": role, "event_id": None}
        _insert_link(conn, evidence_id, target_type, target_id, role)
        event_id = append_event(
            conn=conn, events_path=paths.events_path, event_type="evidence_link_added",
            entity_type="evidence", entity_id=evidence_id,
            payload={"evidence_id": evidence_id, "target_type": target_type, "target_id": target_id, "role": role, "summary": summary},
        )
        conn.commit()
        return {"ok": True, "changed": True, "evidence_id": evidence_id, "target": {"type": target_type, "id": target_id}, "role": role, "event_id": event_id}
    finally:
        conn.close()


def apply_structural_actions(paths: ProjectPaths, actions: list[dict[str, Any]]) -> dict[str, Any]:
    from .lifecycle_repair import validate_lifecycle_repair_actions

    require_initialized(paths)
    validate_lifecycle_repair_actions(actions)
    selected = [a for a in actions if a.get("classification") == "structural" and a.get("safe_to_apply") is True]
    if not selected:
        return {"ok": True, "changed": False, "applied_action_ids": [], "event_id": None, "relationships": []}
    conn = connect_mutation(paths)
    try:
        relationships = []
        for action in selected:
            evidence_id, target_type, target_id, role = _structural_relationship(action)
            _validate_evidence_link(paths, conn, evidence_id, target_type, target_id, role)
            if _link_exists(conn, evidence_id, target_type, target_id, role):
                raise _error("repair_stale_precondition", "Structural repair precondition changed before apply.", action_id=action.get("action_id"))
            _insert_link(conn, evidence_id, target_type, target_id, role)
            relationships.append({"evidence_id": evidence_id, "target_type": target_type, "target_id": target_id, "role": role, "before": False, "after": True})
        event_id = append_event(
            conn=conn, events_path=paths.events_path,
            event_type="lifecycle_structural_repair_applied", entity_type="lifecycle_repair", entity_id=None,
            payload={"action_ids": [a["action_id"] for a in selected], "action_kinds": [a["action_kind"] for a in selected], "relationships": relationships},
        )
        conn.commit()
        return {"ok": True, "changed": True, "applied_action_ids": [a["action_id"] for a in selected], "event_id": event_id, "relationships": relationships}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _preflight_test(paths: ProjectPaths, test_id: str, story_id: str | None, evidence_id: str | None) -> None:
    conn = connect(paths.db_path)
    try:
        _validate_test_links(paths, conn, test_id, story_id, evidence_id)
    finally:
        conn.close()


def _preflight_evidence_link(paths: ProjectPaths, evidence_id: str, target_type: str, target_id: str, role: str) -> None:
    conn = connect(paths.db_path)
    try:
        _validate_evidence_link(paths, conn, evidence_id, target_type, target_id, role)
    finally:
        conn.close()


def _validate_test_links(paths: ProjectPaths, conn: sqlite3.Connection, test_id: str, story_id: str | None, evidence_id: str | None) -> sqlite3.Row:
    test = conn.execute("SELECT id, feature_id, story_id, evidence_id, status, last_run_id FROM test_cases WHERE id = ?", (test_id,)).fetchone()
    if test is None:
        raise _error("test_link_unknown_test", f"Test case does not exist: {test_id}", test_case_id=test_id)
    if story_id is not None:
        story = conn.execute("SELECT id, feature_id, status FROM user_stories WHERE id = ?", (story_id,)).fetchone()
        if story is None:
            raise _error("test_link_unknown_story", f"Story does not exist: {story_id}", story_id=story_id)
        if story["feature_id"] != test["feature_id"]:
            raise _error("test_link_cross_feature_story", f"Story {story_id} belongs to another Feature.", test_case_id=test_id, story_id=story_id)
        if test["status"] == "passing" and story["status"] not in {"approved", "waived"}:
            raise _error("test_link_story_not_terminal", f"Passing Test {test_id} requires an approved or waived Story.", story_id=story_id, story_status=story["status"])
    if evidence_id is not None:
        require_healthy_terminal_evidence(paths, conn, evidence_id=evidence_id, error_code="test_link_invalid_evidence", allowed_types=ADHOC_EVIDENCE_TYPES)
        _validate_exclusive_target(conn, evidence_id, "test_case", test_id, "acceptance")
    return test


def _validate_evidence_link(paths: ProjectPaths, conn: sqlite3.Connection, evidence_id: str, target_type: str, target_id: str, role: str) -> None:
    if target_type not in TARGET_TABLES:
        raise _error("evidence_link_unknown_target_type", f"Unknown Evidence target type: {target_type}", target_type=target_type)
    if role in RESERVED_LINK_ROLES:
        raise _error(
            "evidence_link_reserved_role",
            f"Role {role} is owned by `{RESERVED_LINK_ROLES[role]}` and cannot be added generically.",
            role=role,
            dedicated_command=RESERVED_LINK_ROLES[role],
        )
    if role not in ROLE_TARGETS or target_type not in ROLE_TARGETS[role]:
        raise _error("evidence_link_incompatible_role", f"Role {role} is not compatible with {target_type}.", target_type=target_type, role=role)
    if conn.execute(f"SELECT 1 FROM {TARGET_TABLES[target_type]} WHERE id = ?", (target_id,)).fetchone() is None:
        raise _error("evidence_link_unknown_target", f"Target does not exist: {target_type}:{target_id}", target_type=target_type, target_id=target_id)
    evidence = conn.execute("SELECT id, type, path FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    if evidence is None:
        raise _error("evidence_link_unknown_evidence", f"Evidence does not exist: {evidence_id}", evidence_id=evidence_id)
    if role == "acceptance" and target_type == "test_case":
        test = conn.execute("SELECT status, evidence_id FROM test_cases WHERE id = ?", (target_id,)).fetchone()
        if test["status"] == "passing" and test["evidence_id"] != evidence_id:
            raise _error("evidence_link_test_pointer_mismatch", "Terminal Test Evidence pointer differs; use `pcl test link`.", test_case_id=target_id, evidence_id=evidence_id, stored_evidence_id=test["evidence_id"])
        require_healthy_terminal_evidence(paths, conn, evidence_id=evidence_id, error_code="evidence_link_invalid_acceptance", allowed_types=ADHOC_EVIDENCE_TYPES)
    if role == "acceptance" and target_type == "feature":
        require_healthy_terminal_evidence(
            paths,
            conn,
            evidence_id=evidence_id,
            error_code="evidence_link_invalid_acceptance",
            allowed_types=ADHOC_EVIDENCE_TYPES,
        )
    if role == "completion_packet":
        if evidence["type"] != "completion_packet" or not _packet_matches(paths, str(evidence["path"]), target_type, target_id):
            raise _error("evidence_link_packet_target_mismatch", "Completion packet is invalid or targets another entity.", evidence_id=evidence_id, target_type=target_type, target_id=target_id)
    _validate_exclusive_target(conn, evidence_id, target_type, target_id, role)


def _validate_exclusive_target(conn: sqlite3.Connection, evidence_id: str, target_type: str, target_id: str, role: str) -> None:
    if role not in EXCLUSIVE_TARGET_BOUND_ROLES:
        return
    conflicts = conn.execute("SELECT target_type, target_id FROM evidence_links WHERE evidence_id = ? AND link_role = ? AND NOT (target_type = ? AND target_id = ?)", (evidence_id, role, target_type, target_id)).fetchall()
    if conflicts:
        raise _error("evidence_link_exclusive_conflict", f"Evidence {evidence_id} already has a conflicting {role} target.", evidence_id=evidence_id, role=role)


def _packet_matches(paths: ProjectPaths, path_value: str, target_type: str, target_id: str) -> bool:
    path = Path(path_value)
    if not path.is_absolute():
        path = paths.root / path
    try:
        packet = load_completion_packet(path)
    except (OSError, ValueError, TypeError):
        return False
    target = packet.get("target") if isinstance(packet, dict) else None
    return (
        validate_completion_packet(packet).ok
        and isinstance(target, dict)
        and target.get("type") == target_type
        and target.get("id") == target_id
    )


def _structural_relationship(action: dict[str, Any]) -> tuple[str, str, str, str]:
    entity = action.get("entity", {})
    related = action.get("related", [])
    evidence = next((item for item in related if item.get("type") == "evidence"), None)
    if not evidence or not entity.get("type") or not entity.get("id"):
        raise _error("repair_invalid_action", "Structural repair action lacks its public relationship fields.", action_id=action.get("action_id"))
    role = "acceptance" if action["action_kind"] == "add_missing_evidence_link" else "completion_packet"
    return str(evidence["id"]), str(entity["type"]), str(entity["id"]), role


def _insert_link(conn: sqlite3.Connection, evidence_id: str, target_type: str, target_id: str, role: str) -> None:
    conn.execute("INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at) VALUES (?, ?, ?, ?, ?)", (evidence_id, target_type, target_id, role, utc_now_iso()))


def _link_exists(conn: sqlite3.Connection, evidence_id: str, target_type: str, target_id: str, role: str) -> bool:
    return conn.execute("SELECT 1 FROM evidence_links WHERE evidence_id = ? AND target_type = ? AND target_id = ? AND link_role = ?", (evidence_id, target_type, target_id, role)).fetchone() is not None


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _require_summary(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise InvalidInputError("--summary must not be empty.", details={"field": "summary"})
    return cleaned


def _error(code: str, message: str, **details: Any) -> RelationshipRepairError:
    return RelationshipRepairError(message, code=code, details=details)
