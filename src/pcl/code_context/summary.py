from __future__ import annotations

from typing import Any


CODE_CONTEXT_SUMMARY_VERSION = "code-context-summary/v0"


def summarize_code_context_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the stable context-pack summary for a context-receipt/v0 payload."""
    payload = receipt if isinstance(receipt, dict) else {}
    included = _dict_list(payload.get("included_candidate_context"))
    omitted = _dict_list(payload.get("omitted"))
    excluded_changed = _dict_list(payload.get("excluded_changed_files"))
    diff_source = _text(payload.get("diff_source")) or "unknown"
    staleness_warnings = _string_list(payload.get("staleness_warnings"))

    summary: dict[str, Any] = {
        "contract_version": CODE_CONTEXT_SUMMARY_VERSION,
        "status": "from_receipt",
        "receipt_ref": {
            "evidence_id": _text(payload.get("evidence_id")),
            "receipt_path": _text(payload.get("receipt_path")),
        },
        "diff_source": diff_source,
        "index_run": _index_run_summary(payload.get("index_run")),
        "included_candidate_context_count": len(included),
        "included_candidate_context": [_candidate_summary(item) for item in included],
        "omitted_count": len(omitted),
        "omitted": [_omitted_summary(item) for item in omitted],
        "excluded_changed_file_count": len(excluded_changed),
        "excluded_changed_files": [_excluded_changed_summary(item) for item in excluded_changed],
        "sensitive_omitted_count": _int(payload.get("sensitive_omitted_count")),
        "staleness_warnings": staleness_warnings,
        "untracked_omission_warning": _untracked_omission_warning(diff_source),
        "verification_suggestions": _string_list(payload.get("verification_suggestions")),
    }
    base_ref = _text(payload.get("base_ref"))
    if base_ref:
        summary["base_ref"] = base_ref
    return summary


def _candidate_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": _text(item.get("path")),
        "role": _text(item.get("role")),
        "selection": "included as candidate context",
        "reason": _text(item.get("reason")),
        "language": _text(item.get("language")),
        "snapshot_consistency": _text(item.get("snapshot_consistency")),
        "snapshot_consistency_reason": _text(item.get("snapshot_consistency_reason")),
    }
    confidence = _number(item.get("confidence"))
    if confidence is not None:
        summary["confidence"] = confidence
    return _without_empty_values(summary)


def _omitted_summary(item: dict[str, Any]) -> dict[str, Any]:
    return _without_empty_values(
        {
            "path": _text(item.get("path")),
            "omitted_type": _text(item.get("omitted_type")),
            "reason": _text(item.get("reason")),
        }
    )


def _excluded_changed_summary(item: dict[str, Any]) -> dict[str, Any]:
    return _without_empty_values(
        {
            "path": _text(item.get("path")),
            "status": _text(item.get("status")),
            "reason": _text(item.get("reason")),
        }
    )


def _index_run_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _without_empty_values(
        {
            "id": _text(value.get("id")),
            "index_version": _text(value.get("index_version")),
            "git_head": _text(value.get("git_head")),
            "created_at": _text(value.get("created_at")),
        }
    )


def _untracked_omission_warning(diff_source: str) -> str | None:
    if diff_source.startswith("worktree-vs-"):
        return (
            "Untracked files are not included in this diff source; add them to Git "
            "or provide an explicit diff with `pcl impact --diff - --json`."
        )
    return None


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item))]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _without_empty_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != ""
    }
