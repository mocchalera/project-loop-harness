from __future__ import annotations

from collections import Counter
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
    if enabled and not dry_run:
        raise InvalidInputError(
            "Finish output projection flags require --emit-packet --dry-run.",
            details={"field": "finish_output_projection"},
        )
    if enabled:
        _validate_projection_options(
            summary=summary,
            paginate=output_offset is not None or output_limit is not None,
            output_offset=output_offset,
            output_limit=output_limit,
        )
    return enabled


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
