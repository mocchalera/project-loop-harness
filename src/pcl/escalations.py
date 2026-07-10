from __future__ import annotations

from typing import Any

from .db import connect, connect_mutation
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .links import enrich_escalations_with_links, has_escalation_link
from .paths import ProjectPaths
from .timeutil import utc_now_iso


SEVERITIES = {"critical", "high", "medium", "low"}
ESCALATION_STATUSES = {"open", "resolved", "cancelled"}


def open_escalation(
    paths: ProjectPaths,
    *,
    severity: str,
    question: str,
    recommendation: str = "",
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _require_severity(severity)
    _require_text(question, "--question is required to open an escalation.")
    if workflow_run_id:
        _validate_identifier(workflow_run_id, "workflow_run_id")
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        if workflow_run_id:
            _require_workflow_run(conn, workflow_run_id)
        escalation_id = next_prefixed_id(conn, "escalations", "ESC")
        cleaned_question = question.strip()
        cleaned_recommendation = recommendation.strip()
        conn.execute(
            """
            INSERT INTO escalations(id, workflow_run_id, severity, question, recommendation, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                escalation_id,
                workflow_run_id,
                severity,
                cleaned_question,
                cleaned_recommendation,
                "open",
                now,
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="escalation_opened",
            entity_type="escalation",
            entity_id=escalation_id,
            payload={
                "severity": severity,
                "question": cleaned_question,
                "recommendation": cleaned_recommendation,
                "workflow_run_id": workflow_run_id,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": escalation_id,
            "workflow_run_id": workflow_run_id,
            "severity": severity,
            "question": cleaned_question,
            "recommendation": cleaned_recommendation,
            "status": "open",
        }
    finally:
        conn.close()


def resolve_escalation(
    paths: ProjectPaths,
    *,
    escalation_id: str,
    summary: str,
    decision_id: str | None = None,
) -> dict[str, Any]:
    return _close_escalation(
        paths,
        escalation_id=escalation_id,
        summary=summary,
        status="resolved",
        event_type="escalation_resolved",
        decision_id=decision_id,
    )


def cancel_escalation(paths: ProjectPaths, *, escalation_id: str, summary: str) -> dict[str, Any]:
    return _close_escalation(
        paths,
        escalation_id=escalation_id,
        summary=summary,
        status="cancelled",
        event_type="escalation_cancelled",
    )


def list_escalations(paths: ProjectPaths, *, status: str | None = None) -> list[dict[str, Any]]:
    require_initialized(paths)
    if status is not None:
        _require_status(status)
    conn = connect(paths.db_path)
    try:
        if status is None:
            rows = conn.execute(
                """
                SELECT id, workflow_run_id, severity, question, recommendation, status, created_at, resolved_at
                FROM escalations
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, workflow_run_id, severity, question, recommendation, status, created_at, resolved_at
                FROM escalations
                WHERE status = ?
                ORDER BY created_at DESC, id DESC
                """,
                (status,),
            ).fetchall()
        return enrich_escalations_with_links(
            [dict(row) for row in rows],
            _decision_link_rows(conn),
        )
    finally:
        conn.close()


def read_escalation(paths: ProjectPaths, escalation_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(escalation_id, "escalation_id")
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, workflow_run_id, severity, question, recommendation, status, created_at, resolved_at
            FROM escalations
            WHERE id = ?
            """,
            (escalation_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Escalation does not exist: {escalation_id}",
                details={"escalation_id": escalation_id},
            )
        return enrich_escalations_with_links([dict(row)], _decision_link_rows(conn))[0]
    finally:
        conn.close()


def _close_escalation(
    paths: ProjectPaths,
    *,
    escalation_id: str,
    summary: str,
    status: str,
    event_type: str,
    decision_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(escalation_id, "escalation_id")
    if decision_id:
        _validate_identifier(decision_id, "decision_id")
    _require_text(summary, "--summary is required to close an escalation.")
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        escalation = _get_escalation(conn, escalation_id)
        if escalation["status"] != "open":
            raise InvalidInputError(
                f"Escalation {escalation_id} is {escalation['status']} and cannot transition to {status}.",
                details={
                    "escalation_id": escalation_id,
                    "status": escalation["status"],
                    "requested_status": status,
                },
            )
        if decision_id:
            _require_linked_decision(conn, decision_id, escalation_id)
        conn.execute(
            "UPDATE escalations SET status = ?, resolved_at = ? WHERE id = ?",
            (status, now, escalation_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="escalation",
            entity_id=escalation_id,
            payload={
                "summary": summary.strip(),
                "severity": escalation["severity"],
                "question": escalation["question"],
                "recommendation": escalation["recommendation"],
                "workflow_run_id": escalation["workflow_run_id"],
                "decision_id": decision_id,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": escalation_id,
            "workflow_run_id": escalation["workflow_run_id"],
            "severity": escalation["severity"],
            "status": status,
            "summary": summary.strip(),
            "decision_id": decision_id,
        }
    finally:
        conn.close()


def _get_escalation(conn, escalation_id: str):
    row = conn.execute(
        """
        SELECT id, workflow_run_id, severity, question, recommendation, status
        FROM escalations
        WHERE id = ?
        """,
        (escalation_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Escalation does not exist: {escalation_id}",
            details={"escalation_id": escalation_id},
        )
    return row


def _require_workflow_run(conn, workflow_run_id: str) -> None:
    row = conn.execute("SELECT id FROM workflow_runs WHERE id = ?", (workflow_run_id,)).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Workflow run does not exist: {workflow_run_id}",
            details={"workflow_run_id": workflow_run_id},
        )


def _decision_link_rows(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, blocks_json FROM decisions ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _require_linked_decision(conn, decision_id: str, escalation_id: str) -> None:
    row = conn.execute(
        "SELECT id, blocks_json FROM decisions WHERE id = ?",
        (decision_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Decision does not exist: {decision_id}",
            details={"decision_id": decision_id},
        )
    if not has_escalation_link(str(row["blocks_json"] or "[]"), escalation_id):
        raise InvalidInputError(
            f"Decision {decision_id} is not linked to escalation {escalation_id}.",
            details={"decision_id": decision_id, "escalation_id": escalation_id},
        )


def _require_severity(severity: str) -> None:
    if severity not in SEVERITIES:
        raise InvalidInputError(
            f"Invalid escalation severity: {severity}",
            details={"severity": severity, "allowed": sorted(SEVERITIES)},
        )


def _require_status(status: str) -> None:
    if status not in ESCALATION_STATUSES:
        raise InvalidInputError(
            f"Invalid escalation status: {status}",
            details={"status": status, "allowed": sorted(ESCALATION_STATUSES)},
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
