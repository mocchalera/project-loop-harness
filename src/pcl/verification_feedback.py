from __future__ import annotations

import json
from json import JSONDecodeError
import sqlite3
from typing import Any

from .code_context.receipts import (
    CONTEXT_RECEIPT_EVIDENCE_TYPE,
    CONTEXT_RECEIPT_VERSION,
    resolve_context_receipt_path,
)
from .db import connect, connect_mutation, table_exists
from .evidence import ADHOC_EVIDENCE_TYPES, assess_adhoc_evidence
from .errors import EXIT_USAGE, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso


FEEDBACK_STATUSES = {"executed", "skipped", "not_applicable"}
FEEDBACK_RESULTS = {"passed", "failed", "inconclusive"}


class VerificationFeedbackError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code=code,
            exit_code=EXIT_USAGE,
            details=details or {},
        )


def record_verification_feedback(
    paths: ProjectPaths,
    *,
    suggestion_id: str,
    status: str,
    result: str | None = None,
    supporting_evidence_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    suggestion_id = suggestion_id.strip()
    status = status.strip()
    result = _clean_optional(result)
    supporting_evidence_id = _clean_optional(supporting_evidence_id)
    note = _clean_optional(note)
    _validate_status_result_evidence(
        status=status,
        result=result,
        supporting_evidence_id=supporting_evidence_id,
    )
    receipt_evidence_id = _receipt_evidence_id_from_suggestion(suggestion_id)
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        receipt_row = _context_receipt_row(conn, receipt_evidence_id)
        if receipt_row is None:
            raise VerificationFeedbackError(
                f"Suggestion {suggestion_id} references an unknown context receipt {receipt_evidence_id}.",
                code="verification_feedback_unknown_receipt",
                details={
                    "suggestion_id": suggestion_id,
                    "receipt_evidence_id": receipt_evidence_id,
                },
            )
        receipt = _load_receipt_payload(paths, receipt_row)
        if not _receipt_contains_suggestion(receipt, suggestion_id):
            raise VerificationFeedbackError(
                f"Suggestion ID {suggestion_id} is not present in receipt {receipt_evidence_id}.",
                code="verification_feedback_suggestion_absent",
                details={
                    "suggestion_id": suggestion_id,
                    "receipt_evidence_id": receipt_evidence_id,
                },
            )
        if supporting_evidence_id is not None and not _evidence_exists(conn, supporting_evidence_id):
            raise VerificationFeedbackError(
                f"Supporting evidence does not exist: {supporting_evidence_id}.",
                code="verification_feedback_missing_evidence",
                details={"supporting_evidence_id": supporting_evidence_id},
            )

        feedback_id = next_prefixed_id(conn, "verification_feedback", "VF")
        conn.execute(
            """
            INSERT INTO verification_feedback(
              id, suggestion_id, receipt_evidence_id, status, result,
              supporting_evidence_id, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                suggestion_id,
                receipt_evidence_id,
                status,
                result,
                supporting_evidence_id,
                note,
                now,
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="verification_feedback_recorded",
            entity_type="verification_feedback",
            entity_id=feedback_id,
            payload={
                "suggestion_id": suggestion_id,
                "receipt_evidence_id": receipt_evidence_id,
                "status": status,
                "result": result,
                "supporting_evidence_id": supporting_evidence_id,
                "note": note,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "feedback": {
                "id": feedback_id,
                "suggestion_id": suggestion_id,
                "receipt_evidence_id": receipt_evidence_id,
                "status": status,
                "result": result,
                "supporting_evidence_id": supporting_evidence_id,
                "note": note,
                "created_at": now,
            },
        }
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def verification_feedback_stats(paths: ProjectPaths) -> dict[str, Any]:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        receipt_rows = conn.execute(
            """
            SELECT id, type, path, created_at
            FROM evidence
            WHERE type = ?
            ORDER BY created_at, id
            """,
            (CONTEXT_RECEIPT_EVIDENCE_TYPE,),
        ).fetchall()
        addressable_suggestion_ids: set[str] = set()
        unaddressable_legacy_count = 0
        warnings: list[str] = []
        unreadable_count = 0

        for row in receipt_rows:
            try:
                receipt = _load_receipt_payload(paths, row)
            except VerificationFeedbackError as exc:
                unreadable_count += 1
                warnings.append(exc.message)
                continue
            addressable, unaddressable = _suggestion_counts_from_receipt(receipt)
            addressable_suggestion_ids.update(addressable)
            unaddressable_legacy_count += unaddressable

        feedback_rows = _feedback_rows_for_suggestions(conn, addressable_suggestion_ids)
        supporting_evidence_health = _supporting_evidence_health(paths, conn, feedback_rows)
    finally:
        conn.close()

    suggestions_with_feedback: set[str] = set()
    suggestions_with_executed_feedback: set[str] = set()
    executed_feedback_events = 0
    executed_pass_events = 0
    executed_fail_events = 0
    latest_feedback_by_suggestion: dict[str, dict[str, Any]] = {}

    for row in feedback_rows:
        suggestion_id = str(row["suggestion_id"])
        status = str(row["status"])
        result = row["result"]
        suggestions_with_feedback.add(suggestion_id)
        if status == "executed":
            suggestions_with_executed_feedback.add(suggestion_id)
            executed_feedback_events += 1
            if result == "passed":
                executed_pass_events += 1
            elif result == "failed":
                executed_fail_events += 1
        summary = _feedback_row_summary(row)
        summary["supporting_evidence_health"] = _health_for_feedback_row(row, supporting_evidence_health)
        latest_feedback_by_suggestion[suggestion_id] = summary

    addressable_count = len(addressable_suggestion_ids)
    feedback_coverage_numerator = len(suggestions_with_feedback)
    execution_numerator = len(suggestions_with_executed_feedback)
    return {
        "ok": True,
        "stats": {
            "receipts_scanned": len(receipt_rows),
            "receipts_unreadable_count": unreadable_count,
            "warnings": warnings,
            "addressable_issued_suggestions_count": addressable_count,
            "unaddressable_legacy_suggestions_count": unaddressable_legacy_count,
            "feedback_coverage_numerator": feedback_coverage_numerator,
            "feedback_coverage_denominator": addressable_count,
            "feedback_coverage_rate": _rate(feedback_coverage_numerator, addressable_count),
            "execution_numerator": execution_numerator,
            "execution_denominator": addressable_count,
            "execution_rate": _rate(execution_numerator, addressable_count),
            "executed_pass_numerator": executed_pass_events,
            "executed_pass_denominator": executed_feedback_events,
            "executed_pass_rate": _rate(executed_pass_events, executed_feedback_events),
            "executed_fail_numerator": executed_fail_events,
            "executed_fail_denominator": executed_feedback_events,
            "executed_fail_rate": _rate(executed_fail_events, executed_feedback_events),
            "executed_feedback_events_count": executed_feedback_events,
            "supporting_evidence_health": supporting_evidence_health,
            "latest_feedback_by_suggestion": dict(sorted(latest_feedback_by_suggestion.items())),
        },
    }


def _validate_status_result_evidence(
    *,
    status: str,
    result: str | None,
    supporting_evidence_id: str | None,
) -> None:
    if status not in FEEDBACK_STATUSES:
        raise VerificationFeedbackError(
            f"Invalid feedback status: {status}.",
            code="verification_feedback_invalid_status",
            details={"status": status, "allowed": sorted(FEEDBACK_STATUSES)},
        )
    if result is not None and result not in FEEDBACK_RESULTS:
        raise VerificationFeedbackError(
            f"Invalid feedback result: {result}.",
            code="verification_feedback_invalid_result",
            details={"result": result, "allowed": sorted(FEEDBACK_RESULTS)},
        )
    if status == "executed":
        if result is None:
            raise VerificationFeedbackError(
                "Feedback with status executed requires --result.",
                code="verification_feedback_result_required",
                details={"status": status},
            )
        if supporting_evidence_id is None:
            raise VerificationFeedbackError(
                "Feedback with status executed requires --evidence.",
                code="verification_feedback_evidence_required",
                details={"status": status},
            )
        return
    if result is not None:
        raise VerificationFeedbackError(
            f"Feedback with status {status} must not include --result.",
            code="verification_feedback_result_not_allowed",
            details={"status": status, "result": result},
        )


def _receipt_evidence_id_from_suggestion(suggestion_id: str) -> str:
    if "/" not in suggestion_id:
        raise VerificationFeedbackError(
            "Suggestion IDs must include the receipt evidence prefix, for example 'E-0001/VS-01'.",
            code="verification_feedback_invalid_suggestion_id",
            details={"suggestion_id": suggestion_id},
        )
    receipt_evidence_id = suggestion_id.split("/", 1)[0].strip()
    if not receipt_evidence_id:
        raise VerificationFeedbackError(
            "Suggestion ID is missing the receipt evidence prefix.",
            code="verification_feedback_invalid_suggestion_id",
            details={"suggestion_id": suggestion_id},
        )
    return receipt_evidence_id


def _context_receipt_row(conn: sqlite3.Connection, evidence_id: str) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT id, type, path, created_at
        FROM evidence
        WHERE id = ?
        """,
        (evidence_id,),
    ).fetchone()
    if row is None or str(row["type"]) != CONTEXT_RECEIPT_EVIDENCE_TYPE:
        return None
    return row


def _load_receipt_payload(paths: ProjectPaths, row: sqlite3.Row) -> dict[str, Any]:
    receipt_path_value = str(row["path"] or "")
    receipt_path = resolve_context_receipt_path(paths, receipt_path_value)
    try:
        raw = receipt_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, JSONDecodeError) as exc:
        raise VerificationFeedbackError(
            f"Context receipt artifact is unreadable for evidence {row['id']}: {receipt_path_value}.",
            code="verification_feedback_unreadable_receipt",
            details={
                "receipt_evidence_id": str(row["id"]),
                "receipt_path": receipt_path_value,
            },
        ) from exc
    if not isinstance(payload, dict):
        raise VerificationFeedbackError(
            f"Context receipt artifact is not a JSON object for evidence {row['id']}: {receipt_path_value}.",
            code="verification_feedback_unreadable_receipt",
            details={
                "receipt_evidence_id": str(row["id"]),
                "receipt_path": receipt_path_value,
            },
        )
    if payload.get("contract_version") != CONTEXT_RECEIPT_VERSION:
        raise VerificationFeedbackError(
            f"Context receipt artifact has an unsupported contract for evidence {row['id']}: {receipt_path_value}.",
            code="verification_feedback_unreadable_receipt",
            details={
                "receipt_evidence_id": str(row["id"]),
                "receipt_path": receipt_path_value,
                "contract_version": payload.get("contract_version"),
            },
        )
    return payload


def _receipt_contains_suggestion(receipt: dict[str, Any], suggestion_id: str) -> bool:
    suggestions = receipt.get("verification_suggestions")
    if not isinstance(suggestions, list):
        return False
    for item in suggestions:
        if isinstance(item, dict) and _clean_optional(item.get("id")) == suggestion_id:
            return True
    return False


def _evidence_exists(conn: sqlite3.Connection, evidence_id: str) -> bool:
    return conn.execute("SELECT 1 FROM evidence WHERE id = ?", (evidence_id,)).fetchone() is not None


def _suggestion_counts_from_receipt(receipt: dict[str, Any]) -> tuple[set[str], int]:
    suggestions = receipt.get("verification_suggestions")
    if not isinstance(suggestions, list):
        return set(), 0
    addressable: set[str] = set()
    unaddressable = 0
    for item in suggestions:
        if isinstance(item, dict):
            suggestion_id = _clean_optional(item.get("id"))
            if suggestion_id is None:
                unaddressable += 1
            else:
                addressable.add(suggestion_id)
            continue
        if _clean_optional(item) is not None:
            unaddressable += 1
    return addressable, unaddressable


def _feedback_rows_for_suggestions(
    conn: sqlite3.Connection,
    suggestion_ids: set[str],
) -> list[sqlite3.Row]:
    if not suggestion_ids or not table_exists(conn, "verification_feedback"):
        return []
    placeholders = ", ".join("?" for _ in suggestion_ids)
    return conn.execute(
        f"""
        SELECT id, suggestion_id, receipt_evidence_id, status, result,
               supporting_evidence_id, note, created_at
        FROM verification_feedback
        WHERE suggestion_id IN ({placeholders})
        ORDER BY created_at, id
        """,
        tuple(sorted(suggestion_ids)),
    ).fetchall()


def _supporting_evidence_health(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    feedback_rows: list[sqlite3.Row],
) -> dict[str, Any]:
    feedback_evidence_ids = [
        evidence_id
        for evidence_id in (_clean_optional(row["supporting_evidence_id"]) for row in feedback_rows)
        if evidence_id is not None
    ]
    distinct_evidence_ids = sorted(set(feedback_evidence_ids))
    evidence_rows = _evidence_rows_by_id(conn, distinct_evidence_ids)
    by_evidence_id: dict[str, dict[str, Any]] = {}
    health_counts = {"ok": 0, "warning": 0, "error": 0, "unknown": 0}

    for evidence_id in distinct_evidence_ids:
        row = evidence_rows.get(evidence_id)
        if row is None:
            assessment = {
                "health": "error",
                "findings": [{"code": "evidence_row_missing"}],
            }
        else:
            evidence_type = str(row["type"] or "")
            if evidence_type in ADHOC_EVIDENCE_TYPES:
                assessment = assess_adhoc_evidence(
                    paths,
                    evidence_id=evidence_id,
                    evidence_type=evidence_type,
                    manifest_path_value=str(row["path"] or ""),
                )
            else:
                assessment = {
                    "health": "unknown",
                    "findings": [
                        {
                            "code": "health_not_assessed_for_type",
                            "detail": evidence_type,
                        }
                    ],
                }
        health = str(assessment.get("health") or "unknown")
        if health not in health_counts:
            health = "unknown"
            assessment = {
                "health": health,
                "findings": [{"code": "health_not_assessed_for_type", "detail": "unknown"}],
            }
        by_evidence_id[evidence_id] = assessment
        health_counts[health] += 1

    return {
        "assessed_evidence_count": len(distinct_evidence_ids),
        "feedback_events_with_supporting_evidence_count": len(feedback_evidence_ids),
        "health_counts": health_counts,
        "by_evidence_id": by_evidence_id,
    }


def _evidence_rows_by_id(
    conn: sqlite3.Connection,
    evidence_ids: list[str],
) -> dict[str, sqlite3.Row]:
    if not evidence_ids:
        return {}
    placeholders = ", ".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"""
        SELECT id, type, path
        FROM evidence
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        tuple(evidence_ids),
    ).fetchall()
    return {str(row["id"]): row for row in rows}


def _health_for_feedback_row(
    row: sqlite3.Row,
    supporting_evidence_health: dict[str, Any],
) -> str | None:
    evidence_id = _clean_optional(row["supporting_evidence_id"])
    if evidence_id is None:
        return None
    assessment = supporting_evidence_health["by_evidence_id"].get(evidence_id)
    if not isinstance(assessment, dict):
        return "unknown"
    return str(assessment.get("health") or "unknown")


def _feedback_row_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "status": str(row["status"]),
        "result": row["result"],
        "receipt_evidence_id": str(row["receipt_evidence_id"]),
        "supporting_evidence_id": row["supporting_evidence_id"],
        "note": row["note"],
        "created_at": str(row["created_at"]),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
