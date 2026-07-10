from __future__ import annotations

from datetime import date
import json
from json import JSONDecodeError
from typing import Any

from .context_usage import CONTEXT_PACK_GENERATED_EVENT
from .db import connect
from .errors import InvalidInputError
from .guards import require_initialized
from .paths import ProjectPaths
from .verification_feedback import verification_feedback_stats


KPI_REPORT_CONTRACT_VERSION = "kpi-report/v1"
OPT_IN_CONTEXT_PACK_SCOPE = "recorded_opt_in_context_packs_only"
COMPLETION_PACKET_CREATED_EVENT = "completion_packet_created"
FINISH_ROUNDTRIP_SOURCE = "manual:finish_roundtrip_comparison"
READ_ONLY_RESUME_SOURCE = "read_only_operation:pcl_resume"


def report_kpi(paths: ProjectPaths, *, since: str | None = None) -> dict[str, Any]:
    require_initialized(paths)
    normalized_since = _normalize_since(since)
    window = {"since": normalized_since, "until": None}
    verification_stats = verification_feedback_stats(paths, since=normalized_since)["stats"]
    context_rows = _context_pack_events(paths, since=normalized_since)
    finish_rows = _event_payloads(
        paths,
        event_type=COMPLETION_PACKET_CREATED_EVENT,
        since=normalized_since,
    )

    return {
        "ok": True,
        "contract_version": KPI_REPORT_CONTRACT_VERSION,
        "sections": {
            "verification_spend_efficiency": _verification_section(
                verification_stats,
                window=window,
            ),
            "context_pack": _context_pack_section(context_rows, window=window),
            "finish": _finish_section(finish_rows, window=window),
            "handoff": _unmeasured_section(
                metrics=("resume_execution_count", "packet_generation_count"),
                data_source=READ_ONLY_RESUME_SOURCE,
                reason="read_only_operation_not_recorded",
                window=window,
            ),
        },
    }


def _verification_section(stats: dict[str, Any], *, window: dict[str, str | None]) -> dict[str, Any]:
    source = "verification_feedback_stats:verification_feedback+evidence"
    execution_rate = stats["execution_rate"]
    executed_pass_rate = stats["executed_pass_rate"]
    efficiency = (
        None
        if execution_rate is None or executed_pass_rate is None
        else round(float(execution_rate) * float(executed_pass_rate), 4)
    )
    return {
        "execution_rate": _metric(
            execution_rate,
            reason="no_data_in_window" if execution_rate is None else None,
            data_source=source,
            window=window,
        ),
        "executed_pass_rate": _metric(
            executed_pass_rate,
            reason="no_data_in_window" if executed_pass_rate is None else None,
            data_source=source,
            window=window,
        ),
        "feedback_coverage_rate": _metric(
            stats["feedback_coverage_rate"],
            reason="no_data_in_window" if stats["feedback_coverage_rate"] is None else None,
            data_source=source,
            window=window,
        ),
        "verification_spend_efficiency": _metric(
            efficiency,
            reason="no_data_in_window" if efficiency is None else None,
            data_source=source,
            window=window,
        ),
    }


def _context_pack_section(
    rows: list[dict[str, Any]],
    *,
    window: dict[str, str | None],
) -> dict[str, Any]:
    source = f"events:{CONTEXT_PACK_GENERATED_EVENT}"
    count = len(rows)
    tokens = [int(row["estimated_token_count"]) for row in rows]
    bound_count = sum(1 for row in rows if row["bound_receipt"] is True)
    reason = "no_data_in_window" if count == 0 else None
    return {
        "measurement_scope": OPT_IN_CONTEXT_PACK_SCOPE,
        "generation_count": _metric(count, data_source=source, window=window),
        "average_context_pack_tokens": _metric(
            round(sum(tokens) / count, 2) if count else None,
            reason=reason,
            data_source=source,
            window=window,
        ),
        "bound_receipt_coverage": _metric(
            round(bound_count / count, 4) if count else None,
            reason=reason,
            data_source=source,
            window=window,
        ),
    }


def _finish_section(
    rows: list[dict[str, Any]],
    *,
    window: dict[str, str | None],
) -> dict[str, Any]:
    source = f"events:{COMPLETION_PACKET_CREATED_EVENT}"
    outcome_counts: dict[str, int] = {}
    for row in rows:
        outcome = row.get("outcome")
        if not isinstance(outcome, str) or not outcome:
            raise InvalidInputError(
                f"Invalid {COMPLETION_PACKET_CREATED_EVENT} event payload.",
                details={"event_type": COMPLETION_PACKET_CREATED_EVENT},
            )
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

    return {
        "finish_execution_count": _metric(
            len(rows),
            data_source=source,
            window=window,
        ),
        "packet_outcome_distribution": _metric(
            dict(sorted(outcome_counts.items())) if rows else None,
            reason="no_data_in_window" if not rows else None,
            data_source=source,
            window=window,
        ),
        "finish_roundtrips_saved": _metric(
            None,
            reason="manual_comparison_not_recorded",
            data_source=FINISH_ROUNDTRIP_SOURCE,
            window=window,
        ),
    }


def _unmeasured_section(
    *,
    metrics: tuple[str, ...],
    data_source: str,
    reason: str,
    window: dict[str, str | None],
) -> dict[str, Any]:
    return {
        name: _metric(
            None,
            reason=reason,
            data_source=data_source,
            window=window,
        )
        for name in metrics
    }


def _metric(
    value: Any,
    *,
    data_source: str,
    window: dict[str, str | None],
    reason: str | None = None,
) -> dict[str, Any]:
    metric = {"value": value, "data_source": data_source, "window": dict(window)}
    if reason is not None:
        metric["reason"] = reason
    return metric


def _context_pack_events(paths: ProjectPaths, *, since: str | None) -> list[dict[str, Any]]:
    return _event_payloads(paths, event_type=CONTEXT_PACK_GENERATED_EVENT, since=since)


def _event_payloads(
    paths: ProjectPaths,
    *,
    event_type: str,
    since: str | None,
) -> list[dict[str, Any]]:
    conn = connect(paths.db_path)
    try:
        sql = """
            SELECT payload_json
            FROM events
            WHERE event_type = ?
        """
        params: list[Any] = [event_type]
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(since)
        sql += " ORDER BY sequence"
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()

    payloads: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except JSONDecodeError as exc:
            raise InvalidInputError(
                f"Invalid {event_type} event payload.",
                details={"event_type": event_type},
            ) from exc
        if not isinstance(payload, dict):
            raise InvalidInputError(
                f"Invalid {event_type} event payload.",
                details={"event_type": event_type},
            )
        payloads.append(payload)
    return payloads


def _normalize_since(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise InvalidInputError(
            "--since must be an ISO date in YYYY-MM-DD format.",
            details={"since": value},
        ) from exc
