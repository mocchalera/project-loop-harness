from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


TERMINAL_READINESS_CONTRACT_VERSION = "terminal-readiness/v1"
READINESS_STATES = {"satisfied", "advisory", "risk", "incomplete", "blocked"}
_REASON_STATE_ORDER = {
    "blocked": 0,
    "incomplete": 1,
    "risk": 2,
    "advisory": 3,
}


def evaluate_terminal_readiness(
    *,
    target_type: str,
    target_id: str,
    requirements: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate normalized terminal requirements without reading or mutating state."""
    normalized_target_type = _required_text(target_type, "target_type")
    normalized_target_id = _required_text(target_id, "target_id")
    reasons = [
        _normalize_requirement(requirement)
        for requirement in requirements
        if str(requirement.get("state", "")).strip() != "satisfied"
    ]
    reasons = _dedupe_reasons(reasons)
    reasons.sort(key=_reason_sort_key)

    states = {reason["state"] for reason in reasons}
    if "blocked" in states:
        status = "blocked"
    elif "incomplete" in states:
        status = "incomplete"
    elif "risk" in states:
        status = "ready_with_risk"
    else:
        status = "ready"

    next_commands: list[str] = []
    for reason in reasons:
        command = reason.get("next_command")
        if command and command not in next_commands:
            next_commands.append(command)

    return {
        "contract_version": TERMINAL_READINESS_CONTRACT_VERSION,
        "target": {
            "type": normalized_target_type,
            "id": normalized_target_id,
        },
        "status": status,
        "terminal_allowed": status in {"ready", "ready_with_risk"},
        "requires_human": any(reason["requires_human"] for reason in reasons),
        "reasons": reasons,
        "next_commands": next_commands,
    }


def feature_terminal_readiness(
    *,
    feature_id: str,
    stories: Iterable[Mapping[str, Any]],
    tests: Iterable[Mapping[str, Any]],
    defects: Iterable[Mapping[str, Any]],
    additional_requirements: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    normalized_feature_id = _required_text(feature_id, "feature_id")
    story_rows = _normalized_entity_rows(stories)
    test_rows = [
        row for row in _normalized_entity_rows(tests) if row["status"] != "waived"
    ]
    defect_rows = [
        row
        for row in _normalized_entity_rows(defects)
        if row["status"] not in {"closed", "waived"}
    ]
    incomplete_stories = [
        row for row in story_rows if row["status"] not in {"approved", "waived"}
    ]
    incomplete_tests = [row for row in test_rows if row["status"] != "passing"]

    requirements: list[Mapping[str, Any]] = []
    if not story_rows or incomplete_stories:
        requirements.append(
            {
                "code": "feature_done_story_incomplete",
                "state": "blocked",
                "message": (
                    f"Feature {normalized_feature_id} has missing or incomplete Stories."
                ),
                "requires_human": bool(incomplete_stories),
                "next_command": f"pcl feature read {normalized_feature_id} --json",
                "details": {
                    "feature_id": normalized_feature_id,
                    "stories": incomplete_stories,
                    "story_count": len(story_rows),
                },
            }
        )
    if not test_rows or incomplete_tests:
        first_test_id = incomplete_tests[0]["id"] if incomplete_tests else None
        requirements.append(
            {
                "code": "feature_done_tests_incomplete",
                "state": "incomplete",
                "message": (
                    f"Feature {normalized_feature_id} has missing or incomplete "
                    "non-waived Tests."
                ),
                "next_command": (
                    f"pcl test read {first_test_id} --json"
                    if first_test_id
                    else f"pcl feature read {normalized_feature_id} --json"
                ),
                "details": {
                    "feature_id": normalized_feature_id,
                    "tests": incomplete_tests,
                    "test_count": len(test_rows),
                },
            }
        )
    if defect_rows:
        requirements.append(
            {
                "code": "feature_done_open_defects",
                "state": "blocked",
                "message": f"Feature {normalized_feature_id} has active Defects.",
                "next_command": f"pcl feature read {normalized_feature_id} --json",
                "details": {
                    "feature_id": normalized_feature_id,
                    "defects": defect_rows,
                },
            }
        )
    requirements.extend(additional_requirements)
    return evaluate_terminal_readiness(
        target_type="feature",
        target_id=normalized_feature_id,
        requirements=requirements,
    )


def finish_terminal_readiness(
    *,
    target_type: str,
    target_id: str,
    commands: Iterable[Mapping[str, Any]],
    strict_ok: bool,
    strict_errors: Iterable[str],
    strict_warnings: Iterable[str],
    race_detected: bool,
    blockers: Mapping[str, Any],
    stability_mode: str,
    additional_requirements: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    command_rows = [dict(command) for command in commands]
    errors = [str(error) for error in strict_errors]
    warnings = [str(warning) for warning in strict_warnings]
    decisions = [
        dict(item) for item in blockers.get("decisions", []) if isinstance(item, Mapping)
    ]
    escalations = [
        dict(item)
        for item in blockers.get("escalations", [])
        if isinstance(item, Mapping)
    ]
    human_steps = [
        dict(item)
        for item in blockers.get("human_steps", [])
        if isinstance(item, Mapping)
    ]
    requirements: list[Mapping[str, Any]] = []

    if blockers.get("budget_exhausted") is True:
        requirements.append(
            {
                "code": "finish_budget_exhausted",
                "state": "blocked",
                "message": "The target Goal budget is exhausted.",
                "details": {"budget_exhausted": True},
            }
        )
    if decisions or escalations or human_steps:
        requirements.append(
            {
                "code": "finish_human_decision_required",
                "state": "blocked",
                "message": "A recorded human decision is required before completion.",
                "requires_human": True,
                "next_command": "pcl decision list --status open",
                "details": {
                    "decisions": decisions,
                    "escalations": escalations,
                    "human_steps": human_steps,
                },
            }
        )
    if race_detected:
        requirements.append(
            {
                "code": "finish_repository_race",
                "state": "incomplete",
                "message": "The repository changed while finish checks were running.",
                "details": {"race_detected": True},
            }
        )
    if not strict_ok or errors:
        requirements.append(
            {
                "code": "finish_strict_validation_failed",
                "state": "incomplete",
                "message": "Strict project validation did not pass.",
                "next_command": "pcl validate --strict --json",
                "details": {"errors": errors},
            }
        )

    failed_commands = [
        {
            "command": str(command.get("command") or ""),
            "status": str(command.get("status") or "unknown"),
        }
        for command in command_rows
        if command.get("status") != "passed"
    ]
    if failed_commands:
        requirements.append(
            {
                "code": "finish_checks_incomplete",
                "state": "incomplete",
                "message": "One or more configured finish checks did not pass.",
                "details": {"commands": failed_commands},
            }
        )
    if warnings:
        requirements.append(
            {
                "code": "finish_strict_validation_warning",
                "state": "risk",
                "message": "Strict project validation reported warnings.",
                "next_command": "pcl validate --strict --json",
                "details": {"warnings": warnings},
            }
        )

    unstable = [
        {
            "command": str(command.get("command") or ""),
            "status": str(evaluation.get("status") or "unknown"),
            "reproducible": evaluation.get("reproducible") is True,
        }
        for command in command_rows
        if isinstance(
            evaluation := command.get("stability_evaluation"),
            Mapping,
        )
        and evaluation.get("reproducible") is not True
    ]
    if unstable:
        requirements.append(
            {
                "code": (
                    "finish_stability_record_only"
                    if stability_mode == "record_only"
                    else "finish_stability_incomplete"
                ),
                "state": "advisory" if stability_mode == "record_only" else "incomplete",
                "message": (
                    "Stability observations are recorded but not terminally enforced."
                    if stability_mode == "record_only"
                    else "Required stability evidence is incomplete."
                ),
                "details": {
                    "mode": stability_mode,
                    "checks": unstable,
                },
            }
        )

    requirements.extend(additional_requirements)
    return evaluate_terminal_readiness(
        target_type=target_type,
        target_id=target_id,
        requirements=requirements,
    )


def task_terminal_readiness(
    *,
    task_id: str,
    task_status: str,
    feature_id: str | None,
    stories: Iterable[Mapping[str, Any]],
    tests: Iterable[Mapping[str, Any]],
    defects: Iterable[Mapping[str, Any]],
    additional_requirements: Iterable[Mapping[str, Any]] = (),
    evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_task_id = _required_text(task_id, "task_id")
    normalized_task_status = _required_text(task_status, "task_status")
    normalized_feature_id = str(feature_id or "").strip() or None
    requirements: list[Mapping[str, Any]] = []
    if normalized_feature_id is not None:
        feature_readiness = feature_terminal_readiness(
            feature_id=normalized_feature_id,
            stories=stories,
            tests=tests,
            defects=defects,
        )
        requirements.extend(feature_readiness["reasons"])
    requirements.extend(additional_requirements)
    readiness = evaluate_terminal_readiness(
        target_type="task",
        target_id=normalized_task_id,
        requirements=requirements,
    )
    readiness["source_feature_id"] = normalized_feature_id
    readiness["derived_task_status"] = (
        "ready_to_close"
        if normalized_feature_id is not None
        and normalized_task_status in {"todo", "ready", "in_progress"}
        and readiness["terminal_allowed"]
        else normalized_task_status
    )
    readiness["transition"] = {
        "from_status": normalized_task_status,
        "to_status": "done",
    }
    if evaluation is not None:
        readiness["evaluation"] = dict(evaluation)
    return readiness


def canonical_terminal_readiness_input_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def goal_terminal_readiness(
    *,
    goal_id: str,
    tasks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized_goal_id = _required_text(goal_id, "goal_id")
    task_rows = _normalized_entity_rows(tasks)
    incomplete_tasks = [
        row
        for row in task_rows
        if row["status"] not in {"done", "cancelled", "waived"}
    ]
    requirements: list[Mapping[str, Any]] = []
    if incomplete_tasks:
        requirements.append(
            {
                "code": "goal_close_tasks_incomplete",
                "state": "incomplete",
                "message": (
                    f"Goal {normalized_goal_id} cannot close while related Tasks "
                    "are non-terminal."
                ),
                "next_command": f"pcl task read {incomplete_tasks[0]['id']} --json",
                "details": {
                    "goal_id": normalized_goal_id,
                    "incomplete_tasks": incomplete_tasks,
                },
            }
        )
    return evaluate_terminal_readiness(
        target_type="goal",
        target_id=normalized_goal_id,
        requirements=requirements,
    )


def _normalize_requirement(requirement: Mapping[str, Any]) -> dict[str, Any]:
    code = _required_text(str(requirement.get("code", "")), "requirement code")
    state = _required_text(str(requirement.get("state", "")), "requirement state")
    if state not in READINESS_STATES - {"satisfied"}:
        raise ValueError(f"Unsupported readiness requirement state: {state}")
    message = _required_text(str(requirement.get("message", "")), "requirement message")
    next_command = str(requirement.get("next_command") or "").strip() or None
    raw_details = requirement.get("details", {})
    if not isinstance(raw_details, Mapping):
        raise ValueError("Readiness requirement details must be an object.")
    reason = {
        "code": code,
        "state": state,
        "message": message,
        "requires_human": requirement.get("requires_human") is True,
        "next_command": next_command,
        "details": dict(raw_details),
    }
    return {key: value for key, value in reason.items() if value is not None}


def _reason_sort_key(reason: Mapping[str, Any]) -> tuple[int, str, str]:
    return (
        _REASON_STATE_ORDER[str(reason["state"])],
        str(reason["code"]),
        json.dumps(reason["details"], ensure_ascii=False, sort_keys=True),
    )


def _dedupe_reasons(reasons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for reason in reasons:
        normalized = dict(reason)
        key = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        deduped.setdefault(key, normalized)
    return list(deduped.values())


def _normalized_entity_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    normalized = [
        {
            "id": _required_text(str(row.get("id", "")), "entity id"),
            "status": _required_text(str(row.get("status", "")), "entity status"),
        }
        for row in rows
    ]
    return sorted(normalized, key=lambda row: (row["id"], row["status"]))


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")
    return normalized
