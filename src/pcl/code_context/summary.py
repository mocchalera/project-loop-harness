from __future__ import annotations

from datetime import datetime, timezone
import shlex
from typing import Any


CODE_CONTEXT_SUMMARY_VERSION = "code-context-summary/v0"
DEFAULT_INCLUDED_CANDIDATE_LIMIT = 10
INDEX_REFRESH_COMMAND = "pcl index build --json"
IMPACT_REFRESH_COMMAND = "pcl impact --diff --json"
PROVISIONAL_RECEIPT_AGE_WARNING_SECONDS = 3600


def summarize_code_context_receipt(
    receipt: dict[str, Any],
    *,
    included_candidate_limit: int = DEFAULT_INCLUDED_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    """Return the stable context-pack summary for a context-receipt/v0 payload."""
    payload = receipt if isinstance(receipt, dict) else {}
    included = _dict_list(payload.get("included_candidate_context"))
    omitted = _dict_list(payload.get("omitted"))
    changed_files = _dict_list(payload.get("changed_files"))
    excluded_changed = _dict_list(payload.get("excluded_changed_files"))
    diff_source = _text(payload.get("diff_source")) or "unknown"
    staleness_warnings = _string_list(payload.get("staleness_warnings"))
    limit = max(0, included_candidate_limit)
    index_run = payload.get("index_run")

    summary: dict[str, Any] = {
        "contract_version": CODE_CONTEXT_SUMMARY_VERSION,
        "receipt_ref": {
            "evidence_id": _text(payload.get("evidence_id")),
            "receipt_path": _text(payload.get("receipt_path")),
            "created_at": _text(payload.get("created_at")),
        },
        "diff_source": diff_source,
        "index_run": _index_run_summary(index_run),
        "changed_file_count": _changed_file_count(
            changed_files=changed_files,
            included=included,
            excluded_changed=excluded_changed,
            omitted=omitted,
        ),
        "excluded_changed_file_count": len(excluded_changed),
        "sensitive_omitted_count": _int(payload.get("sensitive_omitted_count")),
        "staleness_warnings": staleness_warnings,
        "untracked_omission_warning": _untracked_omission_warning(diff_source),
        "included_total": len(included),
        "included_candidate_context_top": [
            _candidate_summary(item)
            for item in included[:limit]
        ],
        "omitted_reason_counts": _omitted_reason_counts(omitted),
        "verification_suggestions": _verification_suggestion_summaries(
            payload.get("verification_suggestions")
        ),
        "sensitive_include_override_used": _sensitive_include_override_used(index_run),
    }
    untracked_included_count = _optional_int(payload.get("untracked_included_count"))
    if untracked_included_count is not None:
        summary["untracked_included_count"] = untracked_included_count
    base_ref = _text(payload.get("base_ref"))
    if base_ref:
        summary["base_ref"] = base_ref
    summary["refresh_replay"] = refresh_replay(summary)
    return summary


def render_receipt_summary(summary: dict[str, Any]) -> str:
    """Render a code-context-summary/v0 payload for fast human triage."""
    payload = summary if isinstance(summary, dict) else {}
    receipt_ref = payload.get("receipt_ref")
    if not isinstance(receipt_ref, dict):
        receipt_ref = {}

    counts_line = (
        "changed: "
        f"{_display(payload.get('changed_file_count'))}; "
        "excluded changed: "
        f"{_display(payload.get('excluded_changed_file_count'))}; "
        "sensitive omitted: "
        f"{_display(payload.get('sensitive_omitted_count'))}"
    )
    if payload.get("untracked_included_count") is not None:
        counts_line += f"; untracked included: {_display(payload.get('untracked_included_count'))}"

    lines = [
        "# Context Receipt Summary",
        "",
        "## Receipt",
        f"- evidence_id: {_display(receipt_ref.get('evidence_id'))}",
        f"- receipt_path: {_display(receipt_ref.get('receipt_path'))}",
        f"- created_at: {_display(receipt_ref.get('created_at'))}",
        f"- diff_source: {_display(payload.get('diff_source'))}",
        f"- base_ref: {_display(payload.get('base_ref'))}",
        *render_receipt_age_lines(payload),
        "",
        "## Counts",
        counts_line,
        "",
        "## Staleness Warnings",
    ]

    staleness_warnings = _string_list(payload.get("staleness_warnings"))
    if staleness_warnings:
        lines.extend(f"- {warning}" for warning in staleness_warnings)
    else:
        lines.append("None.")

    lines.extend(["", "## Untracked Omission Warning"])
    untracked_warning = _text(payload.get("untracked_omission_warning"))
    lines.append(untracked_warning or "None.")

    lines.extend(
        [
            "",
            "## Included Candidate Context",
            f"included_total: {_display(payload.get('included_total'))}",
        ]
    )
    candidates = _dict_list(payload.get("included_candidate_context_top"))
    if candidates:
        for item in candidates:
            lines.append(_candidate_line(item))
    else:
        lines.append("None.")

    lines.extend(["", "## Omitted Reason Counts"])
    omitted_reason_counts = payload.get("omitted_reason_counts")
    if isinstance(omitted_reason_counts, dict) and omitted_reason_counts:
        for reason, count in omitted_reason_counts.items():
            lines.append(f"- {_display(reason)}: {_display(count)}")
    else:
        lines.append("None.")

    lines.extend(["", "## Verification Suggestions"])
    verification_suggestions = _verification_suggestion_summaries(
        payload.get("verification_suggestions")
    )
    if verification_suggestions:
        lines.extend(
            f"- {format_verification_suggestion_for_display(suggestion)}"
            for suggestion in verification_suggestions
        )
    else:
        lines.append("None.")

    lines.extend(["", "## Next Recommended Command", _next_recommended_command(payload)])
    return "\n".join(lines).rstrip() + "\n"


def summary_with_receipt_age(summary: dict[str, Any], *, now: str) -> dict[str, Any]:
    """Return a copy of a summary with deterministic receipt age fields attached."""
    payload = dict(summary if isinstance(summary, dict) else {})
    receipt_ref = payload.get("receipt_ref")
    created_at = receipt_ref.get("created_at") if isinstance(receipt_ref, dict) else None
    payload.update(receipt_age_fields(created_at, now=now))
    return payload


def receipt_age_fields(created_at: Any, *, now: str) -> dict[str, Any]:
    created_at_text = _text(created_at)
    receipt_age: dict[str, Any] = {"created_at": created_at_text}
    created_at_dt = _parse_timestamp(created_at_text)
    now_dt = _parse_timestamp(now)
    if created_at_dt is None or now_dt is None:
        return {
            "receipt_age": receipt_age,
            "age_warning": (
                "Receipt age could not be computed because created_at is missing "
                "or unparsable."
            ),
        }

    age_seconds = max(0, int((now_dt - created_at_dt).total_seconds()))
    receipt_age["age_seconds"] = age_seconds
    fields: dict[str, Any] = {"receipt_age": receipt_age}
    if age_seconds > PROVISIONAL_RECEIPT_AGE_WARNING_SECONDS:
        fields["age_warning"] = (
            f"Receipt age is {age_seconds}s, above the provisional "
            f"{PROVISIONAL_RECEIPT_AGE_WARNING_SECONDS}s threshold."
        )
    return fields


def render_receipt_age_lines(summary: dict[str, Any]) -> list[str]:
    payload = summary if isinstance(summary, dict) else {}
    receipt_age = payload.get("receipt_age")
    if not isinstance(receipt_age, dict):
        return []

    created_at = _display(receipt_age.get("created_at"))
    lines = []
    age_seconds = receipt_age.get("age_seconds")
    if isinstance(age_seconds, int) and not isinstance(age_seconds, bool):
        lines.append(f"- receipt age: {age_seconds}s (created_at {created_at})")
    else:
        lines.append(f"- receipt age: unknown (created_at {created_at})")

    age_warning = _text(payload.get("age_warning"))
    if age_warning:
        lines.append(f"- age warning: {age_warning}")
    return lines


def _parse_timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _candidate_line(item: dict[str, Any]) -> str:
    path = _display(item.get("path"))
    role = _display(item.get("role"))
    selection = _display(item.get("selection") or "included as candidate context")
    reason = _display(item.get("reason"))
    snapshot_consistency = _display(item.get("snapshot_consistency"))
    return (
        f"- {path}: {selection}; role={role}; reason={reason}; "
        f"snapshot_consistency={snapshot_consistency}"
    )


def recommended_refresh_commands(summary: dict[str, Any]) -> list[str]:
    payload = summary if isinstance(summary, dict) else {}
    replay = payload.get("refresh_replay")
    if isinstance(replay, dict):
        commands = _string_list(replay.get("commands"))
        if commands:
            return commands
    return refresh_replay(payload)["commands"]


def format_verification_suggestion_for_display(value: Any) -> str:
    if isinstance(value, dict):
        command = _text(value.get("command"))
        if command is None:
            return ""
        suggestion_id = _text(value.get("id"))
        if suggestion_id:
            return f"{command} [{suggestion_id}]"
        return command
    return _text(value) or ""


def refresh_replay(summary: dict[str, Any]) -> dict[str, Any]:
    """Return scope-aware commands for refreshing code-context evidence."""
    payload = summary if isinstance(summary, dict) else {}
    next_actions = _string_list(payload.get("next_actions"))
    if next_actions:
        return {
            "fidelity": "unavailable",
            "commands": next_actions,
            "reason": [
                "No replayable context receipt scope is available; follow the next actions to create fresh code-context evidence."
            ],
        }
    status = _text(payload.get("status"))
    staleness_warnings = _string_list(payload.get("staleness_warnings"))
    if status in {"missing_receipt", "unavailable", "receipt_unavailable"}:
        return {
            "fidelity": "unavailable",
            "commands": [INDEX_REFRESH_COMMAND, IMPACT_REFRESH_COMMAND],
            "reason": [
                f"Receipt status was {status or 'unknown'}; no previous diff scope can be replayed."
            ],
        }

    replay = _impact_refresh_replay(payload)
    commands = list(replay["commands"])
    reasons = list(replay["reason"])
    if staleness_warnings:
        commands.insert(0, INDEX_REFRESH_COMMAND)
        reasons.insert(
            0,
            "staleness_warnings were present; refresh should rebuild the code index first.",
        )
    return {
        "fidelity": replay["fidelity"],
        "commands": commands,
        "reason": reasons,
    }


def _impact_refresh_replay(summary: dict[str, Any]) -> dict[str, Any]:
    diff_source = _text(summary.get("diff_source")) or "unknown"
    base_ref = _text(summary.get("base_ref"))
    include_untracked = diff_source.endswith("+untracked")
    base_diff_source = diff_source.removesuffix("+untracked")

    if base_diff_source == "provided-diff":
        return _generic_refresh_replay(
            "diff_source was provided-diff; PLH cannot reconstruct caller-provided diff text from the receipt."
        )
    if base_diff_source == "worktree-vs-index":
        return _scope_preserving_refresh_replay(
            ["--unstaged"],
            include_untracked=include_untracked,
            reason=f"diff_source was {diff_source}.",
        )
    if base_diff_source == "all-changes-vs-HEAD":
        return _scope_preserving_refresh_replay(
            ["--all-changes"],
            include_untracked=False,
            reason=f"diff_source was {diff_source}.",
        )
    if base_diff_source.startswith("staged-vs-"):
        args = ["--staged"]
        if base_ref:
            args.extend(["--base", base_ref])
        return _scope_preserving_refresh_replay(
            args,
            include_untracked=include_untracked,
            reason=f"diff_source was {diff_source}.",
        )
    if base_diff_source.startswith("worktree-vs-"):
        args: list[str] = []
        if base_ref:
            args.extend(["--base", base_ref])
        return _scope_preserving_refresh_replay(
            args,
            include_untracked=include_untracked,
            reason=f"diff_source was {diff_source}.",
        )
    return _generic_refresh_replay(
        f"diff_source was {diff_source}; no scope-preserving replay mapping is available."
    )


def _scope_preserving_refresh_replay(
    args: list[str],
    *,
    include_untracked: bool,
    reason: str,
) -> dict[str, Any]:
    command_args = ["pcl", "impact", "--diff", *args]
    if include_untracked and "--all-changes" not in args:
        command_args.append("--include-untracked")
    command_args.append("--json")
    return {
        "fidelity": "scope_preserving",
        "commands": [_command_string(command_args)],
        "reason": [reason],
    }


def _generic_refresh_replay(reason: str) -> dict[str, Any]:
    return {
        "fidelity": "generic",
        "commands": [IMPACT_REFRESH_COMMAND],
        "reason": [reason],
    }


def _command_string(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _next_recommended_command(summary: dict[str, Any]) -> str:
    return ", then ".join(f"`{action}`" for action in recommended_refresh_commands(summary))


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


def _index_run_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _without_empty_values(
        {
            "id": _text(value.get("id")),
            "created_at": _text(value.get("created_at")),
        }
    )


def _changed_file_count(
    *,
    changed_files: list[dict[str, Any]],
    included: list[dict[str, Any]],
    excluded_changed: list[dict[str, Any]],
    omitted: list[dict[str, Any]],
) -> int:
    if changed_files:
        return len(changed_files)
    included_changed = sum(1 for item in included if item.get("role") == "changed_file")
    omitted_changed = sum(1 for item in omitted if item.get("omitted_type") == "changed_file")
    return included_changed + len(excluded_changed) + omitted_changed


def _omitted_reason_counts(omitted: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in omitted:
        reason = _text(item.get("reason")) or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _sensitive_include_override_used(index_run: Any) -> bool:
    if not isinstance(index_run, dict):
        return False
    return bool(index_run.get("sensitive_include_override_used"))


def _untracked_omission_warning(diff_source: str) -> str | None:
    if _diff_source_includes_untracked(diff_source):
        return None
    if diff_source.startswith("worktree-vs-") or diff_source.startswith("staged-vs-") or diff_source == "worktree-vs-index":
        return (
            "Untracked files are not included in this diff source; add them to Git "
            "or provide an explicit diff with `pcl impact --diff - --json`."
        )
    return None


def _diff_source_includes_untracked(diff_source: str) -> bool:
    return diff_source.endswith("+untracked")


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _verification_suggestion_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    suggestions: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            command = _text(item.get("command"))
            if command is None:
                continue
            suggestion: dict[str, Any] = {
                "id": _text(item.get("id")),
                "command": command,
            }
            reason = _text(item.get("reason"))
            if reason is not None:
                suggestion["reason"] = reason
            suggestions.append(suggestion)
            continue
        command = _text(item)
        if command is not None:
            suggestions.append({"id": None, "command": command})
    return suggestions


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


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _display(value: Any) -> str:
    text = _text(value)
    return text if text is not None else "none"


def _without_empty_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != ""
    }
