from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .errors import InvalidInputError


FINISH_OUTPUT_PROJECTION_CONTRACT_VERSION = "finish-output-projection/v1"
DEFAULT_FINISH_OUTPUT_LIMIT = 100
MAX_FINISH_OUTPUT_LIMIT = 500
MACHINE_STATE_PREFIXES = (
    ".claude/",
    ".codex/",
    ".playwright-cli/",
    ".work/",
)


def project_finish_plan_output(
    plan: dict[str, Any],
    *,
    summary: bool,
    output_offset: int | None,
    output_limit: int | None,
    exclude_machine_state: bool,
) -> dict[str, Any]:
    """Project a finish dry-run for display without changing snapshot semantics."""

    paginate = output_offset is not None or output_limit is not None
    _validate_projection_options(
        summary=summary,
        paginate=paginate,
        output_offset=output_offset,
        output_limit=output_limit,
    )
    mode = "summary" if summary else "page" if paginate else "filtered"
    offset = output_offset or 0
    limit = (
        0
        if summary
        else output_limit
        if output_limit is not None
        else DEFAULT_FINISH_OUTPUT_LIMIT
        if paginate
        else None
    )
    changes = list(plan.get("changes", []))
    harness_local_state = list(plan.get("harness_local_state", []))
    eligible_changes, omitted = _eligible_changes(
        changes,
        exclude_machine_state=exclude_machine_state,
    )
    if summary:
        projected_changes: list[dict[str, Any]] = []
        projected_harness: list[dict[str, Any]] = []
    elif paginate:
        assert limit is not None
        projected_changes = eligible_changes[offset : offset + limit]
        projected_harness = harness_local_state[offset : offset + limit]
    else:
        projected_changes = eligible_changes
        projected_harness = harness_local_state

    repository = plan.get("repository")
    if not isinstance(repository, dict):
        repository = {}
    projected = {
        **plan,
        "changes": projected_changes,
        "harness_local_state": projected_harness,
        "output_projection": {
            "contract_version": FINISH_OUTPUT_PROJECTION_CONTRACT_VERSION,
            "mode": mode,
            "repository_snapshot": {
                "scope": "complete",
                "dirty": repository.get("dirty"),
                "diff_sha256": repository.get("diff_sha256"),
            },
            "machine_state": {
                "excluded_from_display": exclude_machine_state,
                "prefixes": list(MACHINE_STATE_PREFIXES),
                "omitted_count": len(omitted),
                "omitted_by_prefix": dict(
                    sorted(Counter(prefix for _, prefix in omitted).items())
                ),
            },
            "pagination": (
                {"offset": offset, "limit": limit}
                if paginate
                else None
            ),
            "sections": {
                "changes": _section_projection(
                    total_count=len(changes),
                    eligible_count=len(eligible_changes),
                    returned_count=len(projected_changes),
                    offset=offset,
                    limit=limit,
                    summary=summary,
                ),
                "harness_local_state": _section_projection(
                    total_count=len(harness_local_state),
                    eligible_count=len(harness_local_state),
                    returned_count=len(projected_harness),
                    offset=offset,
                    limit=limit,
                    summary=summary,
                ),
            },
        },
    }
    return projected


def project_finish_result_output(
    result: dict[str, Any],
    *,
    summary: bool,
    output_offset: int | None,
    output_limit: int | None,
    exclude_machine_state: bool,
) -> dict[str, Any]:
    """Project an executed finish result without changing durable proof."""

    projected = project_finish_plan_output(
        result,
        summary=summary,
        output_offset=output_offset,
        output_limit=output_limit,
        exclude_machine_state=exclude_machine_state,
    )
    output_projection = dict(projected["output_projection"])
    output_projection["source_mode"] = "actual"
    if not summary:
        return {**projected, "output_projection": output_projection}

    checks = _mapping_list(result.get("checks"))
    check_plan = _mapping_list(result.get("check_plan"))
    execution = _mapping(result.get("execution"))
    strict_validation = _mapping(result.get("strict_validation"))
    terminal_readiness = _mapping(result.get("terminal_readiness"))
    materialization = _mapping(execution.get("materialization"))
    effect = _mapping(execution.get("effect"))
    readiness_reasons = _mapping_list(terminal_readiness.get("reasons"))

    sections = dict(output_projection["sections"])
    sections.update(
        {
            "checks": _summary_section(len(checks), len(checks)),
            "check_plan": _summary_section(len(check_plan), len(check_plan)),
            "execution_materialization_changes": _summary_section(
                len(_mapping_list(materialization.get("changes"))),
                0,
            ),
            "execution_materialization_reasons": _summary_section(
                len(_list(materialization.get("reasons"))),
                0,
            ),
            "execution_effect_changes": _summary_section(
                len(_mapping_list(effect.get("changes"))),
                0,
            ),
            "execution_effect_reasons": _summary_section(
                len(_list(effect.get("reasons"))),
                0,
            ),
            "strict_validation_errors": _summary_section(
                len(_list(strict_validation.get("errors"))),
                0,
            ),
            "strict_validation_warnings": _summary_section(
                len(_list(strict_validation.get("warnings"))),
                0,
            ),
            "terminal_readiness_reasons": _summary_section(
                len(readiness_reasons),
                0,
            ),
        }
    )
    output_projection["sections"] = sections
    return {
        **projected,
        "check_plan": [_compact_check_plan(row) for row in check_plan],
        "checks": [_compact_check(row) for row in checks],
        "execution": _compact_execution(execution),
        "strict_validation": _compact_strict_validation(strict_validation),
        "terminal_readiness": _compact_terminal_readiness(terminal_readiness),
        "output_projection": output_projection,
    }


def validate_finish_output_flags(
    *,
    dry_run: bool,
    summary: bool,
    output_offset: int | None,
    output_limit: int | None,
    exclude_machine_state: bool,
) -> bool:
    enabled = (
        summary
        or output_offset is not None
        or output_limit is not None
        or exclude_machine_state
    )
    _ = dry_run
    if enabled:
        _validate_projection_options(
            summary=summary,
            paginate=output_offset is not None or output_limit is not None,
            output_offset=output_offset,
            output_limit=output_limit,
        )
    return enabled


def _compact_check_plan(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in ("id", "config_key", "safe_to_run", "blocked_reason")
        if key in row
    }


def _compact_check(row: Mapping[str, Any]) -> dict[str, Any]:
    runner_result = _mapping(row.get("runner_result"))
    assertion_result = _mapping(row.get("assertion_result"))
    attempt_identity = _mapping(row.get("attempt_identity"))
    stability = _mapping(row.get("stability_evaluation"))
    reuse = _mapping(row.get("reuse"))
    role_bindings = _mapping_list(reuse.get("role_bindings"))
    compatible_history = _list(reuse.get("compatible_history"))
    compact = {
        "contract_version": row.get("contract_version"),
        "evidence_id": row.get("evidence_id"),
        "artifact_sha256": row.get("artifact_sha256"),
        "status": row.get("status"),
        "exit_code": row.get("exit_code"),
        "failure_phase": row.get("failure_phase"),
        "failure_kind": row.get("failure_kind"),
        "runner_status": runner_result.get("status"),
        "assertion_status": assertion_result.get("status"),
        "output_truncated": bool(row.get("output_truncated")),
        "redacted": bool(row.get("redacted")),
        "attempt_identity_sha256": attempt_identity.get("identity_sha256"),
        "execution_identity_sha256": attempt_identity.get(
            "execution_identity_sha256"
        ),
        "stability_status": stability.get("status"),
        "reproducible": bool(stability.get("reproducible")),
        "attempt_count": stability.get("attempt_count"),
        "remaining_attempts": stability.get("remaining_attempts"),
    }
    if reuse:
        compact["reuse"] = {
            "contract_version": reuse.get("contract_version"),
            "status": reuse.get("status"),
            "reused_role_count": reuse.get("reused_role_count"),
            "role_bindings": role_bindings[:10],
            "role_binding_count": len(role_bindings),
            "compatible_history_count": len(compatible_history),
        }
    return compact


def _compact_execution(execution: Mapping[str, Any]) -> dict[str, Any]:
    if not execution:
        return {}
    workspace = _mapping(execution.get("workspace"))
    return {
        "workspace": {
            key: workspace.get(key)
            for key in ("kind", "temporary", "git_metadata_shared")
            if key in workspace
        },
        "materialization": _compact_effect(execution.get("materialization")),
        "input_before": _compact_manifest(execution.get("input_before")),
        "input_after": _compact_manifest(execution.get("input_after")),
        "effect": _compact_effect(execution.get("effect")),
    }


def _compact_manifest(value: Any) -> dict[str, Any]:
    manifest = _mapping(value)
    return {
        key: manifest.get(key)
        for key in (
            "contract_version",
            "manifest_sha256",
            "ok",
            "entry_count",
            "tracked_count",
            "untracked_count",
            "ignored_count",
            "unknown_count",
        )
        if key in manifest
    }


def _compact_effect(value: Any) -> dict[str, Any]:
    effect = _mapping(value)
    if not effect:
        return {}
    return {
        "classification": effect.get("classification"),
        "change_count": len(_mapping_list(effect.get("changes"))),
        "reason_count": len(_list(effect.get("reasons"))),
    }


def _compact_strict_validation(validation: Mapping[str, Any]) -> dict[str, Any]:
    if not validation:
        return {}
    return {
        "ok": validation.get("ok"),
        "error_count": len(_list(validation.get("errors"))),
        "warning_count": len(_list(validation.get("warnings"))),
    }


def _compact_terminal_readiness(readiness: Mapping[str, Any]) -> dict[str, Any]:
    if not readiness:
        return {}
    reasons = _mapping_list(readiness.get("reasons"))
    reason_counts = Counter(str(reason.get("code") or "unknown") for reason in reasons)
    recovery_commands = _unique_strings(
        [
            *(
                reason.get("next_command")
                for reason in reasons
                if reason.get("next_command")
            ),
            *_list(readiness.get("next_commands")),
        ]
    )
    compact = {
        key: readiness.get(key)
        for key in (
            "contract_version",
            "status",
            "terminal_allowed",
            "requires_human",
            "derived_task_status",
            "source_feature_id",
            "target",
        )
        if key in readiness
    }
    compact.update(
        {
            "reason_count": len(reasons),
            "reason_counts": dict(sorted(reason_counts.items())),
            "reason_codes": sorted(reason_counts),
            "recovery_commands": recovery_commands[:20],
            "recovery_command_count": len(recovery_commands),
        }
    )
    return compact


def _summary_section(total_count: int, returned_count: int) -> dict[str, Any]:
    return {
        "total_count": total_count,
        "eligible_count": total_count,
        "returned_count": returned_count,
        "has_more": total_count > returned_count,
        "next_offset": returned_count if total_count > returned_count else None,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique_strings(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _validate_projection_options(
    *,
    summary: bool,
    paginate: bool,
    output_offset: int | None,
    output_limit: int | None,
) -> None:
    if summary and paginate:
        raise InvalidInputError(
            "--summary cannot be combined with --output-offset or --output-limit.",
            details={
                "summary": True,
                "output_offset": output_offset,
                "output_limit": output_limit,
            },
        )
    if output_offset is not None and output_offset < 0:
        raise InvalidInputError(
            "--output-offset must be at least 0.",
            details={"field": "output_offset", "value": output_offset, "minimum": 0},
        )
    if output_limit is not None and not 1 <= output_limit <= MAX_FINISH_OUTPUT_LIMIT:
        raise InvalidInputError(
            f"--output-limit must be between 1 and {MAX_FINISH_OUTPUT_LIMIT}.",
            details={
                "field": "output_limit",
                "value": output_limit,
                "minimum": 1,
                "maximum": MAX_FINISH_OUTPUT_LIMIT,
            },
        )


def _eligible_changes(
    changes: list[dict[str, Any]],
    *,
    exclude_machine_state: bool,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    if not exclude_machine_state:
        return changes, []
    eligible: list[dict[str, Any]] = []
    omitted: list[tuple[dict[str, Any], str]] = []
    for item in changes:
        path = str(item.get("path") or "")
        prefix = next(
            (candidate for candidate in MACHINE_STATE_PREFIXES if path.startswith(candidate)),
            None,
        )
        if prefix is None:
            eligible.append(item)
        else:
            omitted.append((item, prefix))
    return eligible, omitted


def _section_projection(
    *,
    total_count: int,
    eligible_count: int,
    returned_count: int,
    offset: int,
    limit: int | None,
    summary: bool,
) -> dict[str, Any]:
    if summary:
        has_more = eligible_count > 0
        next_offset = 0 if has_more else None
    elif limit is None:
        has_more = False
        next_offset = None
    else:
        has_more = offset + returned_count < eligible_count
        next_offset = offset + returned_count if has_more else None
    return {
        "total_count": total_count,
        "eligible_count": eligible_count,
        "returned_count": returned_count,
        "has_more": has_more,
        "next_offset": next_offset,
    }
