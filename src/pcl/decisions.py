from __future__ import annotations

from typing import Any

from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .links import enrich_decisions_with_links, merge_escalation_link, normalized_json_array
from .paths import ProjectPaths
from .timeutil import utc_now_iso


DECISION_STATUSES = {"open", "resolved", "waived"}


def open_decision(
    paths: ProjectPaths,
    *,
    question: str,
    recommendation: str,
    blocks_json: str = "[]",
    escalation_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _require_text(question, "--question is required to open a decision.")
    _require_text(recommendation, "--recommendation is required to open a decision.")
    if escalation_id:
        _validate_identifier(escalation_id, "escalation_id")
        normalized_blocks_json = merge_escalation_link(blocks_json, escalation_id)
    else:
        normalized_blocks_json = normalized_json_array(blocks_json, "blocks-json")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        if escalation_id:
            _require_open_escalation(conn, escalation_id)
        decision_id = next_prefixed_id(conn, "decisions", "DEC")
        cleaned_question = question.strip()
        cleaned_recommendation = recommendation.strip()
        conn.execute(
            """
            INSERT INTO decisions(id, status, question, recommendation, blocks_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (decision_id, "open", cleaned_question, cleaned_recommendation, normalized_blocks_json, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="decision_opened",
            entity_type="decision",
            entity_id=decision_id,
            payload={
                "question": cleaned_question,
                "recommendation": cleaned_recommendation,
                "blocks_json": normalized_blocks_json,
                "escalation_id": escalation_id,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": decision_id,
            "status": "open",
            "question": cleaned_question,
            "recommendation": cleaned_recommendation,
            "blocks_json": normalized_blocks_json,
            "escalation_id": escalation_id,
        }
    finally:
        conn.close()


def resolve_decision(
    paths: ProjectPaths,
    *,
    decision_id: str,
    selected_option: str,
    reason: str,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(decision_id, "decision_id")
    _require_text(selected_option, "--selected-option is required to resolve a decision.")
    _require_text(reason, "--reason is required to resolve a decision.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        decision = _get_decision(conn, decision_id)
        if decision["status"] != "open":
            raise InvalidInputError(
                f"Decision {decision_id} is {decision['status']} and cannot transition to resolved.",
                details={
                    "decision_id": decision_id,
                    "status": decision["status"],
                    "requested_status": "resolved",
                },
            )
        cleaned_selected_option = selected_option.strip()
        cleaned_reason = reason.strip()
        conn.execute(
            """
            UPDATE decisions
            SET status = ?, selected_option = ?, reason = ?, resolved_at = ?
            WHERE id = ?
            """,
            ("resolved", cleaned_selected_option, cleaned_reason, now, decision_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="decision_resolved",
            entity_type="decision",
            entity_id=decision_id,
            payload={
                "question": decision["question"],
                "recommendation": decision["recommendation"],
                "selected_option": cleaned_selected_option,
                "reason": cleaned_reason,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": decision_id,
            "status": "resolved",
            "selected_option": cleaned_selected_option,
            "reason": cleaned_reason,
        }
    finally:
        conn.close()


def waive_decision(paths: ProjectPaths, *, decision_id: str, reason: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(decision_id, "decision_id")
    _require_text(reason, "--reason is required to waive a decision.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        decision = _get_decision(conn, decision_id)
        if decision["status"] != "open":
            raise InvalidInputError(
                f"Decision {decision_id} is {decision['status']} and cannot transition to waived.",
                details={
                    "decision_id": decision_id,
                    "status": decision["status"],
                    "requested_status": "waived",
                },
            )
        cleaned_reason = reason.strip()
        conn.execute(
            """
            UPDATE decisions
            SET status = ?, reason = ?, resolved_at = ?
            WHERE id = ?
            """,
            ("waived", cleaned_reason, now, decision_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="decision_waived",
            entity_type="decision",
            entity_id=decision_id,
            payload={
                "question": decision["question"],
                "recommendation": decision["recommendation"],
                "reason": cleaned_reason,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": decision_id,
            "status": "waived",
            "reason": cleaned_reason,
        }
    finally:
        conn.close()


def list_decisions(paths: ProjectPaths, *, status: str | None = None) -> list[dict[str, Any]]:
    require_initialized(paths)
    if status is not None:
        _require_status(status)
    conn = connect(paths.db_path)
    try:
        if status is None:
            rows = conn.execute(
                """
                SELECT id, status, question, recommendation, selected_option, reason, blocks_json, created_at, resolved_at
                FROM decisions
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, status, question, recommendation, selected_option, reason, blocks_json, created_at, resolved_at
                FROM decisions
                WHERE status = ?
                ORDER BY created_at DESC, id DESC
                """,
                (status,),
            ).fetchall()
        return enrich_decisions_with_links([dict(row) for row in rows])
    finally:
        conn.close()


def read_decision(paths: ProjectPaths, decision_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(decision_id, "decision_id")
    conn = connect(paths.db_path)
    try:
        return enrich_decisions_with_links([dict(_get_decision(conn, decision_id))])[0]
    finally:
        conn.close()


def _get_decision(conn, decision_id: str):
    row = conn.execute(
        """
        SELECT id, status, question, recommendation, selected_option, reason, blocks_json, created_at, resolved_at
        FROM decisions
        WHERE id = ?
        """,
        (decision_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Decision does not exist: {decision_id}",
            details={"decision_id": decision_id},
        )
    return row


def _require_open_escalation(conn, escalation_id: str) -> None:
    row = conn.execute("SELECT id, status FROM escalations WHERE id = ?", (escalation_id,)).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Escalation does not exist: {escalation_id}",
            details={"escalation_id": escalation_id},
        )
    if row["status"] != "open":
        raise InvalidInputError(
            f"Escalation {escalation_id} is {row['status']} and cannot be linked to a new decision.",
            details={"escalation_id": escalation_id, "status": row["status"]},
        )


def _require_status(status: str) -> None:
    if status not in DECISION_STATUSES:
        raise InvalidInputError(
            f"Invalid decision status: {status}",
            details={"status": status, "allowed": sorted(DECISION_STATUSES)},
        )


def _require_text(value: str, message: str) -> None:
    if not value.strip():
        raise InvalidInputError(message)


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )
