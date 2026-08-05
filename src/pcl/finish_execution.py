from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any

from . import __version__
from .commands import finish_plan
from .check_result_reuse import (
    CHECK_RESULT_REUSE_CONTRACT_VERSION,
    load_compatible_check_history,
)
from .contracts.completion_packet import (
    COMPLETION_PACKET_CONTRACT_VERSION,
    canonical_json,
    validate_completion_packet,
    with_computed_packet_id,
)
from .db import connect, connect_mutation
from .errors import (
    DataStoreError,
    FinishChecksNotConfiguredError,
    FinishTargetReadinessChangedError,
    InvalidInputError,
)
from .events import append_event
from .evidence import insert_evidence_link, linked_task_provenance
from .finish_recovery import MAX_FINISH_TIMEOUT_SECONDS, finish_timeout_recovery
from .finish_progress import FinishProgressReporter
from .finish_repository import capture_finish_repository_snapshot
from .finish_workspace import isolated_finish_workspace
from .guarded_process import DEFAULT_MAX_OUTPUT_BYTES
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .project_config import finish_check_configuration
from .route_overrides import recorded_route_context
from .runner_observability import (
    finalize_persisted_observability,
    observability_for_result_json,
    verify_runner_observability,
)
from .target_resolver import (
    TaskGoalTargetNotFoundError,
    resolve_routing_target,
)
from .terminal_readiness import evaluate_terminal_readiness, finish_terminal_readiness
from .timeutil import utc_now_iso
from .tasks import task_terminal_readiness_for_row
from .validators import validate_project
from .verification_manifest import (
    canonical_verification_input_manifest_json,
    collect_verification_input_manifest,
    compare_verification_input_manifests,
)
from .verification_results import (
    build_finish_check_result,
    build_verification_attempt_identity,
    evaluate_stability,
)
from .workflow_sandbox import execute_planned_guarded_command, plan_guarded_project_checks


COMPLETION_PACKET_EVIDENCE_TYPE = "completion_packet"
COMPLETION_CHECK_EVIDENCE_TYPE = "completion_check"
COMPLETION_PACKET_LINK_ROLE = "completion_packet"
COMPLETION_CHECK_LINK_ROLE = "verification_check"
FINISH_ATTEMPT_CONTRACT_VERSION = "finish-attempt/v1"
FINISH_ATTEMPT_EVIDENCE_TYPE = "finish_attempt"
FINISH_ATTEMPT_LINK_ROLE = "finish_attempt"
FINISH_STABILITY_MINIMUM_CONSECUTIVE_PASSES = 2
FINISH_STABILITY_MAXIMUM_ATTEMPTS = 3
FINISH_DECLARED_OUTPUT_PATTERNS = (
    ".mypy_cache/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    "**/.mypy_cache/**",
    "**/.pytest_cache/**",
    "**/.ruff_cache/**",
    "**/__pycache__/**",
    "**/*.egg-info/**",
    "__pycache__/**",
    "*.egg-info/**",
    "build/**",
    "dist/**",
    "target/**",
)


def plan_finish_packet(
    paths: ProjectPaths,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    task_id: str | None = None,
    base_revision: str | None = None,
) -> dict[str, Any]:
    plan, _ = _plan_finish_packet(
        paths,
        run_id=run_id,
        goal_id=goal_id,
        task_id=task_id,
        base_revision=base_revision,
    )
    return plan


def _plan_finish_packet(
    paths: ProjectPaths,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    task_id: str | None = None,
    base_revision: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_initialized(paths)
    target, target_binding = _resolve_target(
        paths,
        run_id=run_id,
        goal_id=goal_id,
        task_id=task_id,
    )
    repository = capture_finish_repository_snapshot(
        paths,
        base_revision=base_revision,
    )
    commands = _coalesce_finish_checks(plan_guarded_project_checks(paths))
    input_manifest = collect_verification_input_manifest(
        paths.root,
        declared_output_patterns=FINISH_DECLARED_OUTPUT_PATTERNS,
    )
    plan = {
        "mode": "emit_packet",
        "dry_run": True,
        "target": target,
        "repository": repository["packet_repository"],
        "changes": repository["changes"],
        "harness_local_state": repository["harness_local_state"],
        "check_plan": [_public_check_plan(command) for command in commands],
        "safe_to_execute": (
            bool(commands)
            and input_manifest["ok"]
            and all(command["safe_to_run"] for command in commands)
        ),
        "blocked_checks": [
            _public_check_plan(command) for command in commands if not command["safe_to_run"]
        ],
        "verification_input": _manifest_summary(input_manifest),
        "execution_plan": {
            "workspace": {
                "kind": "independent_git_copy",
                "temporary": True,
                "git_metadata_shared": False,
            },
            "declared_output_patterns": list(FINISH_DECLARED_OUTPUT_PATTERNS),
            "stability_policy": {
                "mode": "record_only",
                "minimum_consecutive_passes": (
                    FINISH_STABILITY_MINIMUM_CONSECUTIVE_PASSES
                ),
                "maximum_attempts": FINISH_STABILITY_MAXIMUM_ATTEMPTS,
                "required_strata": ["cold", "warm"],
                "terminal_enforcement": "deferred_to_shared_readiness",
            },
        },
        "execution_provenance": linked_task_provenance(paths, task_id=target["id"])
        if target["type"] == "task" else None,
    }
    if target_binding is not None:
        plan["target_binding"] = target_binding
    blockers = _target_blockers(paths, target, source="finish_plan")
    if blockers["target_readiness"] is not None:
        plan["terminal_readiness"] = blockers["target_readiness"]
    return plan, input_manifest


def emit_finish_packet(
    paths: ProjectPaths,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    task_id: str | None = None,
    base_revision: str | None = None,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if timeout_seconds < 1:
        raise InvalidInputError("--timeout must be at least 1 second.")
    if timeout_seconds > MAX_FINISH_TIMEOUT_SECONDS:
        raise InvalidInputError(
            f"--timeout must be {MAX_FINISH_TIMEOUT_SECONDS} seconds or less.",
            details={
                "timeout_seconds": timeout_seconds,
                "maximum_timeout_seconds": MAX_FINISH_TIMEOUT_SECONDS,
            },
        )
    if max_output_bytes < 1:
        raise InvalidInputError("--max-output-bytes must be at least 1.")
    configuration = finish_check_configuration(paths.root)
    if not configuration["configured"]:
        raise FinishChecksNotConfiguredError(
            details={
                **configuration,
                "failure_kind": "configuration_missing",
                "next_command": "pcl doctor --json",
            }
        )
    plan, input_manifest = _plan_finish_packet(
        paths,
        run_id=run_id,
        goal_id=goal_id,
        task_id=task_id,
        base_revision=base_revision,
    )
    target = plan["target"]
    progress_reporter = (
        FinishProgressReporter(
            progress_callback,
            target_binding=_progress_target_binding(plan, target),
        )
        if progress_callback is not None
        else None
    )
    if progress_reporter is not None:
        progress_reporter.emit(
            event="finish_started",
            phase="planning",
            status="completed",
        )
    existing = _matching_completion_packet(paths, target=target, repository=plan["repository"])
    if (
        existing is not None
        and existing["outcome"] in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
        and _target_is_terminal(paths, target)
    ):
        existing_requirements = []
        if existing["outcome"] == "COMPLETED_WITH_RISK":
            existing_requirements.append(
                {
                    "code": "existing_completion_with_risk",
                    "state": "risk",
                    "message": "The existing completion packet records accepted risk.",
                    "details": {"outcome": existing["outcome"]},
                }
            )
        result = {
            **plan,
            "dry_run": False,
            "changed": False,
            "idempotent": True,
            "packet": existing,
            "terminal_readiness": evaluate_terminal_readiness(
                target_type=target["type"],
                target_id=target["id"],
                requirements=existing_requirements,
            ),
            "checks": [],
            "exit_code": 0,
        }
        if progress_reporter is not None:
            progress_reporter.finish(
                status="completed",
                outcome=str(existing["outcome"]),
                exit_code=0,
            )
        return result

    commands = _coalesce_finish_checks(plan_guarded_project_checks(paths))
    if not commands:
        raise FinishChecksNotConfiguredError(
            details={
                **configuration,
                "failure_kind": "configuration_missing",
                "next_command": "pcl doctor --json",
            }
        )
    blocked = [command for command in commands if not command["safe_to_run"]]
    if blocked:
        raise InvalidInputError(
            "A configured finish check is not guarded-executor allowlisted.",
            details={"blocked_checks": [_public_check_plan(command) for command in blocked]},
        )

    stage_dir = _stage_check_dir(paths)
    try:
        if progress_reporter is not None:
            progress_reporter.phase_started("workspace_preparation")
        with isolated_finish_workspace(
            paths.root,
            input_manifest=input_manifest,
            commands=commands,
        ) as workspace:
            workspace_before = collect_verification_input_manifest(
                workspace["root"],
                declared_output_patterns=FINISH_DECLARED_OUTPUT_PATTERNS,
            )
            if not workspace_before["ok"]:
                raise InvalidInputError(
                    "The isolated finish workspace input manifest is unhealthy.",
                    details=_manifest_summary(workspace_before),
                )
            materialization = compare_verification_input_manifests(
                input_manifest,
                workspace_before,
            )
            if materialization["classification"] not in {
                "read_only",
                "declared_outputs",
            }:
                raise InvalidInputError(
                    "Canonical verification inputs changed while the isolated workspace was prepared.",
                    details={"materialization_effect": materialization},
                )
            if progress_reporter is not None:
                progress_reporter.phase_finished("workspace_preparation")
            finish_policy = _finish_check_policy(
                commands,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
            if progress_reporter is not None:
                progress_reporter.phase_started("checks")
            for index, command in enumerate(commands, start=1):
                heartbeat = (
                    progress_reporter.start_check(
                        index=index,
                        count=len(commands),
                        config_key=f"project.commands.{command['config_key']}",
                    )
                    if progress_reporter is not None
                    else None
                )
                try:
                    execute_planned_guarded_command(
                        paths,
                        command,
                        run_dir=stage_dir,
                        timeout_seconds=timeout_seconds,
                        max_output_bytes=max_output_bytes,
                        execution_root=workspace["root"],
                        record_observability=True,
                    )
                except Exception:
                    if progress_reporter is not None and heartbeat is not None:
                        progress_reporter.finish_check(
                            heartbeat,
                            status="failed",
                            exit_code=None,
                        )
                    raise
                _verify_command_observability(command, root=paths.root)
                if progress_reporter is not None and heartbeat is not None:
                    progress_reporter.finish_check(
                        heartbeat,
                        status=_progress_check_status(command),
                        exit_code=command.get("exit_code"),
                    )
                _attach_finish_check_contracts(
                    command,
                    paths=paths,
                    target=target,
                    input_manifest=input_manifest,
                    finish_policy=finish_policy,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                )
            if progress_reporter is not None:
                progress_reporter.phase_finished("checks")
            workspace_after = collect_verification_input_manifest(
                workspace["root"],
                declared_output_patterns=FINISH_DECLARED_OUTPUT_PATTERNS,
            )
            effect = compare_verification_input_manifests(
                workspace_before,
                workspace_after,
            )
            execution = {
                "workspace": workspace["public"],
                "materialization": materialization,
                "input_before": _manifest_summary(workspace_before),
                "input_after": _manifest_summary(workspace_after),
                "effect": effect,
            }
        if progress_reporter is not None:
            progress_reporter.phase_started("repository_snapshot")
        after = capture_finish_repository_snapshot(
            paths,
            base_revision=plan["repository"]["base_revision"],
        )
        race_detected = _snapshot_identity(plan) != _snapshot_identity(after)
        if progress_reporter is not None:
            progress_reporter.phase_finished("repository_snapshot")
            progress_reporter.phase_started("strict_validation")
        strict = validate_project(paths, strict=True)
        blockers = _target_blockers(paths, target, source="finish_post_checks")
        target_readiness = blockers.get("target_readiness")
        effect_requirements = (
            list(target_readiness["reasons"])
            if isinstance(target_readiness, dict)
            else []
        )
        if effect["classification"] in {"mutates_inputs", "unknown"}:
            effect_requirements.append(
                {
                    "code": "finish_workspace_input_mutation",
                    "state": "incomplete",
                    "message": (
                        "A finish check changed canonical verification inputs or its "
                        "effect could not be classified."
                    ),
                    "details": {
                        "classification": effect["classification"],
                        "changes": effect["changes"],
                        "reasons": effect["reasons"],
                    },
                }
            )
        terminal_readiness = finish_terminal_readiness(
            target_type=target["type"],
            target_id=target["id"],
            commands=commands,
            strict_ok=strict.ok,
            strict_errors=list(strict.errors),
            strict_warnings=list(strict.warnings),
            race_detected=race_detected,
            blockers=blockers,
            stability_mode=plan["execution_plan"]["stability_policy"]["mode"],
            additional_requirements=effect_requirements,
        )
        if progress_reporter is not None:
            progress_reporter.phase_finished("strict_validation")
        if effect["classification"] in {"mutates_inputs", "unknown"}:
            if progress_reporter is not None:
                progress_reporter.phase_started("evidence_commit")
            committed_attempt = _commit_finish_attempt(
                paths,
                target=target,
                repository=after,
                commands=commands,
                stage_dir=stage_dir,
                input_manifest=input_manifest,
                workspace_before=workspace_before,
                workspace_after=workspace_after,
                execution=execution,
                strict_errors=list(strict.errors),
                strict_warnings=list(strict.warnings),
                race_detected=race_detected,
                expected_target_readiness=plan.get("terminal_readiness"),
            )
            if progress_reporter is not None:
                progress_reporter.phase_finished("evidence_commit")
            result = {
                **plan,
                "dry_run": False,
                "repository": after["packet_repository"],
                "changes": after["changes"],
                "harness_local_state": after["harness_local_state"],
                "changed": True,
                "idempotent": False,
                "race_detected": race_detected,
                "execution": execution,
                "strict_validation": {
                    "ok": strict.ok,
                    "errors": list(strict.errors),
                    "warnings": list(strict.warnings),
                },
                "terminal_readiness": terminal_readiness,
                "checks": committed_attempt["checks"],
                "attempt": committed_attempt["attempt"],
                "target_transition": {
                    "changed": False,
                    "from_status": target["status"],
                    "to_status": target["status"],
                },
                "exit_code": 1,
            }
            recovery = finish_timeout_recovery(
                target=target,
                checks=committed_attempt["checks"],
                timeout_seconds=timeout_seconds,
            )
            if recovery is not None:
                result["timeout_recovery"] = recovery
            if progress_reporter is not None:
                progress_reporter.finish(
                    status=_progress_terminal_status(result),
                    outcome=str(committed_attempt["attempt"]["outcome"]),
                    exit_code=1,
                )
            return result
        outcome = _completion_outcome(
            changes=after["changes"],
            blockers=blockers,
            terminal_readiness=terminal_readiness,
        )
        if progress_reporter is not None:
            progress_reporter.phase_started("evidence_commit")
        committed = _commit_completion_packet(
            paths,
            target=target,
            repository=after,
            commands=commands,
            stage_dir=stage_dir,
            strict_errors=list(strict.errors),
            strict_warnings=list(strict.warnings),
            race_detected=race_detected,
            blockers=blockers,
            outcome=outcome,
            timeout_seconds=timeout_seconds,
            expected_target_readiness=plan.get("terminal_readiness"),
        )
        if progress_reporter is not None:
            progress_reporter.phase_finished("evidence_commit")
    except Exception:
        if progress_reporter is not None:
            progress_reporter.finish(
                status="failed",
                outcome=None,
                exit_code=1,
            )
        raise
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
    result = {
        **plan,
        "dry_run": False,
        "repository": after["packet_repository"],
        "changes": after["changes"],
        "harness_local_state": after["harness_local_state"],
        "changed": True,
        "idempotent": False,
        "race_detected": race_detected,
        "execution": execution,
        "strict_validation": {
            "ok": strict.ok,
            "errors": list(strict.errors),
            "warnings": list(strict.warnings),
        },
        "terminal_readiness": terminal_readiness,
        "checks": committed["checks"],
        "packet": committed["packet"],
        "target_transition": committed["target_transition"],
        **(
            {
                "target_terminal_readiness": committed[
                    "target_terminal_readiness"
                ]
            }
            if committed.get("target_terminal_readiness") is not None
            else {}
        ),
        "exit_code": 1 if outcome == "INCOMPLETE_VALIDATION" else 0,
    }
    recovery = finish_timeout_recovery(
        target=target,
        checks=committed["checks"],
        timeout_seconds=timeout_seconds,
    )
    if recovery is not None:
        result["timeout_recovery"] = recovery
    if progress_reporter is not None:
        progress_reporter.finish(
            status=_progress_terminal_status(result),
            outcome=str(committed["packet"]["outcome"]),
            exit_code=int(result["exit_code"]),
        )
    return result


def _progress_target_binding(
    plan: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, str]:
    binding = plan.get("target_binding")
    if isinstance(binding, dict):
        return {
            "target_type": str(binding["target_type"]),
            "target_id": str(binding["target_id"]),
            "source": str(binding["source"]),
        }
    return {
        "target_type": str(target["type"]),
        "target_id": str(target["id"]),
        "source": "resolved",
    }


def _progress_check_status(command: dict[str, Any]) -> str:
    if bool(command.get("timed_out")):
        return "timed_out"
    return "completed" if command.get("status") == "passed" else "failed"


def _progress_terminal_status(result: dict[str, Any]) -> str:
    checks = result.get("checks")
    if isinstance(checks, list) and any(
        isinstance(check, dict) and check.get("status") == "timed_out"
        for check in checks
    ):
        return "timed_out"
    reference = result.get("packet") or result.get("attempt")
    outcome = (
        str(reference.get("outcome") or "")
        if isinstance(reference, dict)
        else ""
    )
    if outcome in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}:
        return "completed"
    if outcome.startswith("INCOMPLETE") or outcome == "NO_CHANGES":
        return "incomplete"
    return "completed" if int(result.get("exit_code") or 0) == 0 else "failed"


def _resolve_target(
    paths: ProjectPaths,
    *,
    run_id: str | None,
    goal_id: str | None,
    task_id: str | None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    explicit = [value for value in (run_id, goal_id, task_id) if value]
    if len(explicit) > 1:
        raise InvalidInputError("Choose only one of --run, --goal, or --task.")
    conn = connect(paths.db_path)
    try:
        if task_id:
            target = _task_target(conn, task_id)
            return target, {
                "target_type": "task",
                "target_id": task_id,
                "source": "explicit",
            }
        planner = finish_plan(paths, run_id=run_id, goal_id=goal_id)
        selected_goal = planner["target"]["goal"]
        if selected_goal:
            target = _goal_target(conn, str(selected_goal), planner=planner)
            binding = (
                {
                    "target_type": "goal",
                    "target_id": str(selected_goal),
                    "source": "explicit",
                }
                if goal_id
                else None
            )
            return target, binding
        if run_id:
            raise InvalidInputError(
                f"Workflow run {run_id} is not linked to a goal that completion-packet/v1 can target.",
                details={"workflow_run_id": run_id},
            )
        row = conn.execute(
            """
            SELECT id FROM tasks
            WHERE status IN ('in_progress', 'ready', 'todo')
            ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'ready' THEN 1 ELSE 2 END,
                     priority, id
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return _task_target(conn, str(row["id"])), None
    finally:
        conn.close()
    raise InvalidInputError(
        "No active goal or task is available for completion packet emission.",
        details={"run": run_id, "goal": goal_id, "task": task_id},
    )


def _task_target(conn: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    try:
        resolved = resolve_routing_target(
            conn,
            task_id,
            expected_type="task",
        )
    except TaskGoalTargetNotFoundError as exc:
        raise InvalidInputError(
            f"Task does not exist: {task_id}",
            details={"task_id": task_id},
        ) from exc
    row = resolved.row
    return {
        "type": "task",
        "id": str(row["id"]),
        "intent": str(row["description"] or row["title"]),
        "status": str(row["status"]),
        "goal_id": resolved.goal_id,
        "work_brief_ref": None,
        "finish_plan": None,
    }


def _goal_target(conn: sqlite3.Connection, goal_id: str, *, planner: dict[str, Any]) -> dict[str, Any]:
    try:
        resolved = resolve_routing_target(
            conn,
            goal_id,
            expected_type="goal",
        )
    except TaskGoalTargetNotFoundError as exc:
        raise InvalidInputError(
            f"Goal does not exist: {goal_id}",
            details={"goal_id": goal_id},
        ) from exc
    row = resolved.row
    return {
        "type": "goal",
        "id": str(row["id"]),
        "intent": str(row["title"]),
        "status": str(row["status"]),
        "goal_id": str(row["id"]),
        "work_brief_ref": None,
        "finish_plan": planner,
    }


def _target_blockers(
    paths: ProjectPaths,
    target: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN")
        try:
            routing_target = resolve_routing_target(conn, str(target["id"]))
        except TaskGoalTargetNotFoundError as exc:
            raise InvalidInputError(
                f"Finish target does not exist: {target['id']}",
                details={
                    "target": target["id"],
                    "target_type": exc.target_type,
                },
            ) from exc
        decisions = []
        for row in conn.execute(
            "SELECT id, question, blocks_json FROM decisions WHERE status = 'open' ORDER BY id"
        ).fetchall():
            if routing_target.decision_blocks(row["blocks_json"]):
                decisions.append({"id": str(row["id"]), "question": str(row["question"])})
        budget_exhausted = False
        goal_id = target.get("goal_id")
        escalations = []
        if goal_id:
            row = conn.execute("SELECT budget_json FROM goals WHERE id = ?", (goal_id,)).fetchone()
            if row is not None:
                try:
                    budget = json.loads(str(row["budget_json"] or "{}"))
                except json.JSONDecodeError:
                    budget = {}
                budget_exhausted = budget.get("exhausted") is True
            escalations = [
                {
                    "id": str(row["id"]),
                    "question": str(row["question"]),
                    "severity": str(row["severity"]),
                }
                for row in conn.execute(
                    """
                    SELECT escalations.id, escalations.question, escalations.severity
                    FROM escalations
                    JOIN workflow_runs
                      ON workflow_runs.id = escalations.workflow_run_id
                    WHERE escalations.status = 'open'
                      AND workflow_runs.goal_id = ?
                    ORDER BY escalations.id
                    """,
                    (goal_id,),
                ).fetchall()
            ]
        target_readiness = None
        if target["type"] == "task":
            task = conn.execute(
                """
                SELECT id, status, related_feature_id
                FROM tasks
                WHERE id = ?
                """,
                (target["id"],),
            ).fetchone()
            if task is not None:
                target_readiness = task_terminal_readiness_for_row(
                    paths,
                    conn,
                    dict(task),
                    source=source,
                )
    finally:
        conn.close()
    planner = target.get("finish_plan") or {}
    human_steps = [step for step in planner.get("remaining_steps", []) if step.get("requires_human")]
    return {
        "decisions": decisions,
        "escalations": escalations,
        "human_steps": human_steps,
        "budget_exhausted": budget_exhausted,
        "target_readiness": target_readiness,
    }


def _completion_outcome(
    *,
    changes: list[dict[str, Any]],
    blockers: dict[str, Any],
    terminal_readiness: dict[str, Any],
) -> str:
    if blockers["budget_exhausted"]:
        return "INCOMPLETE_BUDGET_EXHAUSTED"
    if blockers["decisions"] or blockers["escalations"] or blockers["human_steps"]:
        return "INCOMPLETE_HUMAN_DECISION_REQUIRED"
    if not terminal_readiness["terminal_allowed"]:
        return "INCOMPLETE_VALIDATION"
    if not changes:
        return "NO_CHANGES"
    return (
        "COMPLETED_WITH_RISK"
        if terminal_readiness["status"] == "ready_with_risk"
        else "COMPLETED_VERIFIED"
    )


def _requires_target_freshness(
    expected_target_readiness: dict[str, Any] | None,
) -> bool:
    return (
        isinstance(expected_target_readiness, dict)
        and expected_target_readiness.get("terminal_allowed") is True
    )


def _resolve_finish_task_snapshot(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target: dict[str, Any],
    expected_target_readiness: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        routing_target = resolve_routing_target(
            conn,
            str(target["id"]),
            expected_type="task",
        )
    except TaskGoalTargetNotFoundError:
        current = evaluate_terminal_readiness(
            target_type="task",
            target_id=str(target["id"]),
            requirements=[
                {
                    "code": "finish_target_missing",
                    "state": "blocked",
                    "message": (
                        f"Finish target Task {target['id']} no longer exists."
                    ),
                    "details": {"task_id": str(target["id"])},
                }
            ],
        )
        raise FinishTargetReadinessChangedError(
            target_id=str(target["id"]),
            expected=expected_target_readiness or {},
            current=current,
        )

    fresh_target = dict(target)
    fresh_target["status"] = str(routing_target.row["status"])
    fresh_target_readiness = task_terminal_readiness_for_row(
        paths,
        conn,
        routing_target.row,
        source="finish_commit",
    )
    if _requires_target_freshness(
        expected_target_readiness
    ) and not _same_terminal_readiness_snapshot(
        expected_target_readiness,
        fresh_target_readiness,
    ):
        raise FinishTargetReadinessChangedError(
            target_id=str(target["id"]),
            expected=expected_target_readiness or {},
            current=fresh_target_readiness,
        )
    return fresh_target, fresh_target_readiness


def _commit_finish_attempt(
    paths: ProjectPaths,
    *,
    target: dict[str, Any],
    repository: dict[str, Any],
    commands: list[dict[str, Any]],
    stage_dir: Path,
    input_manifest: dict[str, Any],
    workspace_before: dict[str, Any],
    workspace_after: dict[str, Any],
    execution: dict[str, Any],
    strict_errors: list[str],
    strict_warnings: list[str],
    race_detected: bool,
    expected_target_readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    for manifest in (input_manifest, workspace_before, workspace_after):
        canonical_verification_input_manifest_json(manifest)
    conn = connect_mutation(paths)
    now = utc_now_iso().replace("+00:00", "Z")
    try:
        if target["type"] == "task" and _requires_target_freshness(
            expected_target_readiness
        ):
            _resolve_finish_task_snapshot(
                paths,
                conn,
                target=target,
                expected_target_readiness=expected_target_readiness,
            )
        check_rows = _store_check_evidence(
            paths,
            conn,
            target=target,
            commands=commands,
            now=now,
        )
        attempt = {
            "contract_version": FINISH_ATTEMPT_CONTRACT_VERSION,
            "attempt_id": "",
            "generated_at": now,
            "outcome": "INCOMPLETE_VALIDATION",
            "target": {
                "type": target["type"],
                "id": target["id"],
                "intent": target["intent"],
            },
            "repository": repository["packet_repository"],
            "changes": repository["changes"],
            "input_manifest": input_manifest,
            "workspace": {
                "metadata": execution["workspace"],
                "materialization": execution["materialization"],
                "before": workspace_before,
                "after": workspace_after,
            },
            "effect": execution["effect"],
            "checks": check_rows,
            "strict_validation": {
                "ok": not strict_errors,
                "errors": strict_errors,
                "warnings": strict_warnings,
            },
            "race_detected": race_detected,
        }
        attempt["attempt_id"] = _finish_attempt_id(attempt)
        attempt_hash = attempt["attempt_id"].removeprefix("fa-sha256:")
        attempt_path = (
            paths.evidence_dir / "finish-attempts" / f"{attempt_hash}.json"
        )
        attempt_path.parent.mkdir(parents=True, exist_ok=True)
        if not attempt_path.exists():
            attempt_path.write_text(
                json.dumps(
                    attempt,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
        attempt_evidence_id = next_prefixed_id(conn, "evidence", "E")
        relative_attempt_path = str(attempt_path.relative_to(paths.root))
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_evidence_id,
                FINISH_ATTEMPT_EVIDENCE_TYPE,
                relative_attempt_path,
                "pcl finish --emit-packet",
                (
                    "Finish attempt INCOMPLETE_VALIDATION "
                    f"({execution['effect']['classification']}) "
                    f"for {target['type']} {target['id']}"
                ),
                now,
            ),
        )
        insert_evidence_link(
            conn,
            evidence_id=attempt_evidence_id,
            target_type=target["type"],
            target_id=target["id"],
            link_role=FINISH_ATTEMPT_LINK_ROLE,
            created_at=now,
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="finish_attempt_recorded",
            entity_type=target["type"],
            entity_id=target["id"],
            payload={
                "contract_version": FINISH_ATTEMPT_CONTRACT_VERSION,
                "attempt_id": attempt["attempt_id"],
                "evidence_id": attempt_evidence_id,
                "path": relative_attempt_path,
                "outcome": attempt["outcome"],
                "effect_classification": execution["effect"]["classification"],
                "input_manifest_sha256": input_manifest["manifest_sha256"],
                "check_evidence_ids": [
                    row["evidence_id"] for row in check_rows
                ],
                "check_results": _check_result_anchors(check_rows),
            },
        )
        conn.commit()
        return {
            "checks": check_rows,
            "attempt": {
                "contract_version": FINISH_ATTEMPT_CONTRACT_VERSION,
                "attempt_id": attempt["attempt_id"],
                "evidence_id": attempt_evidence_id,
                "path": relative_attempt_path,
                "outcome": attempt["outcome"],
                "effect_classification": execution["effect"]["classification"],
            },
        }
    except FinishTargetReadinessChangedError:
        conn.rollback()
        raise
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        raise DataStoreError(f"Could not commit finish attempt: {exc}") from exc
    finally:
        conn.close()


def _commit_completion_packet(
    paths: ProjectPaths, *, target: dict[str, Any], repository: dict[str, Any],
    commands: list[dict[str, Any]], stage_dir: Path, strict_errors: list[str],
    strict_warnings: list[str], race_detected: bool, blockers: dict[str, Any], outcome: str,
    timeout_seconds: int,
    expected_target_readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    conn = connect_mutation(paths)
    now = utc_now_iso().replace("+00:00", "Z")
    try:
        fresh_target = dict(target)
        fresh_target_readiness = None
        if target["type"] == "task":
            fresh_target, fresh_target_readiness = _resolve_finish_task_snapshot(
                paths,
                conn,
                target=target,
                expected_target_readiness=expected_target_readiness,
            )

        check_rows = _store_check_evidence(
            paths,
            conn,
            target=target,
            commands=commands,
            now=now,
        )

        adaptive_route = recorded_route_context(
            paths,
            conn,
            target_type=target["type"],
            target_id=target["id"],
        )
        packet = _build_packet(
            target=target, repository=repository, check_rows=check_rows, outcome=outcome,
            strict_errors=strict_errors, strict_warnings=strict_warnings,
            race_detected=race_detected, blockers=blockers, generated_at=now,
            adaptive_route=adaptive_route,
            timeout_seconds=timeout_seconds,
        )
        validation = validate_completion_packet(packet)
        if not validation.ok:
            raise DataStoreError("Generated completion packet failed validation.", details={"errors": list(validation.errors)})
        packet_hash = packet["packet_id"].removeprefix("cp-sha256:")
        packet_path = paths.evidence_dir / "completion-packets" / f"{packet_hash}.json"
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        if not packet_path.exists():
            packet_path.write_text(canonical_json(packet) + "\n", encoding="utf-8")
        packet_evidence_id = next_prefixed_id(conn, "evidence", "E")
        relative_packet_path = str(packet_path.relative_to(paths.root))
        conn.execute(
            "INSERT INTO evidence(id, type, path, command, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (packet_evidence_id, COMPLETION_PACKET_EVIDENCE_TYPE, relative_packet_path, "pcl finish --emit-packet", f"Completion packet {outcome} for {target['type']} {target['id']}", now),
        )
        insert_evidence_link(conn, evidence_id=packet_evidence_id, target_type=target["type"], target_id=target["id"], link_role=COMPLETION_PACKET_LINK_ROLE, created_at=now)
        transition = _apply_terminal_transition(
            conn,
            paths,
            target=fresh_target,
            outcome=outcome,
            packet_evidence_id=packet_evidence_id,
            now=now,
            terminal_readiness=fresh_target_readiness,
        )
        append_event(
            conn=conn, events_path=paths.events_path, event_type="completion_packet_created",
            entity_type=target["type"], entity_id=target["id"],
            payload={
                "contract_version": COMPLETION_PACKET_CONTRACT_VERSION,
                "packet_id": packet["packet_id"], "evidence_id": packet_evidence_id,
                "path": relative_packet_path, "outcome": outcome,
                "diff_sha256": packet["repository"]["diff_sha256"],
                "check_evidence_ids": [row["evidence_id"] for row in check_rows],
                "check_results": _check_result_anchors(check_rows),
                "target_transition": transition,
                **(
                    {"terminal_readiness": fresh_target_readiness}
                    if fresh_target_readiness is not None
                    else {}
                ),
            },
        )
        conn.commit()
        return {
            "checks": check_rows,
            "packet": {"packet_id": packet["packet_id"], "evidence_id": packet_evidence_id, "path": relative_packet_path, "outcome": outcome},
            "target_transition": transition,
            "target_terminal_readiness": fresh_target_readiness,
        }
    except FinishTargetReadinessChangedError:
        conn.rollback()
        raise
    except (OSError, sqlite3.Error) as exc:
        conn.rollback()
        raise DataStoreError(f"Could not commit completion packet: {exc}") from exc
    finally:
        conn.close()


def _store_check_evidence(
    paths: ProjectPaths,
    conn: sqlite3.Connection,
    *,
    target: dict[str, Any],
    commands: list[dict[str, Any]],
    now: str,
) -> list[dict[str, Any]]:
    check_rows: list[dict[str, Any]] = []
    for command in commands:
        pre_verification = _verify_command_observability(command, root=paths.root)
        pre_verification_ok = pre_verification.get("ok") is True
        observability = command.get("observability")
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        final_dir = paths.evidence_dir / "completion-checks" / evidence_id
        final_dir.mkdir(parents=True, exist_ok=False)
        for key in ("stdout_path", "stderr_path"):
            source = paths.root / str(command[key])
            destination = final_dir / source.name
            source.replace(destination)
            command[key] = str(destination.relative_to(paths.root))
            if isinstance(command.get(key.removesuffix("_path")), dict):
                command[key.removesuffix("_path")]["path"] = command[key]
        result_path = final_dir / "result.json"
        observability = command.get("observability")
        if _has_persisted_observability_paths(observability):
            for key in ("summary_path", "events_path"):
                source_value = observability.get(key)
                if not isinstance(source_value, str):
                    continue
                source = paths.root / source_value
                destination = final_dir / source.name
                if source.exists():
                    source.replace(destination)
                observability[key] = str(destination.relative_to(paths.root))
            artifacts = observability.get("artifacts")
            if isinstance(artifacts, dict):
                for name in ("stdout", "stderr"):
                    item = artifacts.get(name)
                    if isinstance(item, dict):
                        item["path"] = command[name]["path"]
                for name in ("summary", "events"):
                    item = artifacts.get(name)
                    if isinstance(item, dict):
                        item["path"] = observability.get(f"{name}_path")
            command["observability"] = finalize_persisted_observability(
                observability,
                root=paths.root,
                result_path=result_path,
            )
            if not pre_verification_ok:
                _apply_observability_verification(command, pre_verification)

        def write_check_result() -> tuple[dict[str, Any], str]:
            payload = _check_result(command, evidence_id=evidence_id)
            payload["observability"] = observability_for_result_json(
                payload.get("observability", {})
            )
            result_bytes = (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
            result_path.write_bytes(result_bytes)
            result_sha256 = f"sha256:{hashlib.sha256(result_bytes).hexdigest()}"
            payload["artifact_sha256"] = result_sha256
            return payload, result_sha256

        check_payload, result_sha256 = write_check_result()
        if _has_persisted_observability_paths(command.get("observability")):
            command["observability"] = finalize_persisted_observability(
                command["observability"],
                root=paths.root,
                result_path=result_path,
                result_sha256=result_sha256,
            )
            if not pre_verification_ok:
                _apply_observability_verification(command, pre_verification)
            final_verification = _verify_command_observability(
                command,
                root=paths.root,
            )
            if final_verification.get("ok") is not True:
                check_payload, result_sha256 = write_check_result()
                command["observability"] = finalize_persisted_observability(
                    command["observability"],
                    root=paths.root,
                    result_path=result_path,
                    result_sha256=result_sha256,
                )
                if not pre_verification_ok:
                    _apply_observability_verification(command, pre_verification)
                _apply_observability_verification(command, final_verification)
                if pre_verification_ok:
                    raise DataStoreError(
                        "Persisted runner observability failed verification.",
                        details={
                            "failure_kind": final_verification.get("failure_kind"),
                            "issues": final_verification.get("issues", []),
                        },
                    )
            check_payload["observability"] = observability_for_result_json(
                command["observability"]
            )
        relative = str(result_path.relative_to(paths.root))
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                COMPLETION_CHECK_EVIDENCE_TYPE,
                relative,
                command["resolved_command"],
                f"Finish check {command['status']}: {command['resolved_command']}",
                now,
            ),
        )
        insert_evidence_link(
            conn,
            evidence_id=evidence_id,
            target_type=target["type"],
            target_id=target["id"],
            link_role=COMPLETION_CHECK_LINK_ROLE,
            created_at=now,
        )
        check_rows.append(check_payload)
    return check_rows


def _finish_attempt_id(attempt: dict[str, Any]) -> str:
    semantic = {
        key: value for key, value in attempt.items() if key != "attempt_id"
    }
    encoded = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"fa-sha256:{hashlib.sha256(encoded).hexdigest()}"


def _build_packet(
    *, target: dict[str, Any], repository: dict[str, Any], check_rows: list[dict[str, Any]],
    outcome: str, strict_errors: list[str], strict_warnings: list[str], race_detected: bool,
    blockers: dict[str, Any], generated_at: str,
    adaptive_route: dict[str, Any] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    checks = [
        {
            "id": f"CHK-{index:04d}", "command": row["command"], "status": row["status"],
            "exit_code": row["exit_code"], "artifact_ref": f"evidence:{row['evidence_id']}",
            "reproducible": bool(
                row.get("stability_evaluation", {}).get("reproducible")
            ),
            "reason": row["reason"],
        }
        for index, row in enumerate(check_rows, start=1)
    ]
    evidence_refs = [check["artifact_ref"] for check in checks if check["status"] == "passed"]
    completed = outcome in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"}
    claims = ([{
        "id": "CL-0001", "text": "All configured finish checks passed for the captured repository snapshot.",
        "critical": True, "proof_level": "L2", "evidence_refs": evidence_refs,
    }] if completed else [])
    reasons = list(strict_errors)
    if race_detected:
        reasons.append("Repository changed while finish checks were running.")
    failed = [check["command"] for check in checks if check["status"] != "passed"]
    if failed:
        reasons.append("Configured checks did not pass: " + ", ".join(failed))
    human_decisions = [item["question"] for item in blockers["decisions"]]
    human_decisions.extend(item["question"] for item in blockers["escalations"])
    human_decisions.extend(str(step["reason"]) for step in blockers["human_steps"])
    recovery = finish_timeout_recovery(
        target=target,
        checks=check_rows,
        timeout_seconds=timeout_seconds,
    )
    next_action = _next_action(outcome, target, timeout_recovery=recovery)
    packet = {
        "contract_version": COMPLETION_PACKET_CONTRACT_VERSION,
        "packet_id": "cp-sha256:" + "0" * 64,
        "producer": {"name": "project-loop-harness", "version": __version__},
        "generated_at": generated_at,
        "outcome": outcome,
        "target": {"type": target["type"], "id": target["id"], "intent": target["intent"], "work_brief_ref": target["work_brief_ref"]},
        "repository": repository["packet_repository"],
        "changes": repository["changes"],
        "harness_local_state": repository["harness_local_state"],
        "checks": checks, "claims": claims,
        "unverified_claims": [
            {"text": reason, "reason": "Finish did not establish a completed outcome.", "critical": False}
            for reason in reasons
        ],
        "risks": [], "human_decisions": human_decisions, "next_action": next_action,
        "verifier_provenance": {"kind": "tool", "name": "pcl finish", "version": __version__, "evidence_ref": evidence_refs[-1] if evidence_refs else None},
    }
    if strict_warnings and outcome == "COMPLETED_WITH_RISK":
        packet["risks"] = [{"severity": "low", "text": warning, "mitigation": "Review strict validation warning."} for warning in strict_warnings]
    if adaptive_route is not None:
        packet["adaptive_route"] = {
            key: adaptive_route[key]
            for key in (
                "contract_version",
                "override_ref",
                "override_sha256",
                "original_recommendation_ref",
                "original_recommendation_sha256",
                "original_resolution_ref",
                "original_resolution_sha256",
                "effective_profile",
                "risk_level",
            )
        }
    return with_computed_packet_id(packet)


def _next_action(
    outcome: str,
    target: dict[str, Any],
    *,
    timeout_recovery: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    command = f"pcl finish --emit-packet --{target['type']} {target['id']}"
    if outcome == "INCOMPLETE_VALIDATION":
        if timeout_recovery is not None and timeout_recovery["available"]:
            suggested_timeout_seconds = timeout_recovery["suggested_timeout_seconds"]
            return {
                "text": (
                    "A finish check timed out. Retry once with the bounded "
                    f"{suggested_timeout_seconds}-second timeout."
                ),
                "command": timeout_recovery["retry_command"],
            }
        if timeout_recovery is not None:
            return {
                "text": (
                    "A finish check timed out at the "
                    f"{MAX_FINISH_TIMEOUT_SECONDS}-second limit. Inspect its "
                    "Evidence before changing the check or retrying."
                ),
                "command": timeout_recovery["diagnostic_command"],
            }
        return {"text": "Fix failed checks or repository drift, then rerun finish.", "command": command}
    if outcome == "INCOMPLETE_BUDGET_EXHAUSTED":
        return {"text": "Review and explicitly extend or close the exhausted budget.", "command": None}
    if outcome == "INCOMPLETE_HUMAN_DECISION_REQUIRED":
        return {"text": "Resolve the recorded human decision before completing the target.", "command": "pcl decision list --status open"}
    if outcome == "NO_CHANGES":
        return {"text": "Provide acceptance Evidence or make the intended repository change.", "command": command}
    return None


def _apply_terminal_transition(
    conn: sqlite3.Connection, paths: ProjectPaths, *, target: dict[str, Any], outcome: str,
    packet_evidence_id: str, now: str,
    terminal_readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    if outcome not in {"COMPLETED_VERIFIED", "COMPLETED_WITH_RISK"} or target["type"] != "task":
        return {"changed": False, "from_status": target["status"], "to_status": target["status"]}
    if target["status"] == "done":
        return {"changed": False, "from_status": "done", "to_status": "done"}
    if terminal_readiness is None or not terminal_readiness["terminal_allowed"]:
        raise FinishTargetReadinessChangedError(
            target_id=str(target["id"]),
            expected=terminal_readiness or {},
            current=terminal_readiness or {},
        )
    conn.execute("UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?", (now, target["id"]))
    append_event(
        conn=conn, events_path=paths.events_path, event_type="task_status_changed",
        entity_type="task", entity_id=target["id"],
        payload={
            "from_status": target["status"],
            "to_status": "done",
            "reason": "Completion packet checks passed.",
            "evidence_id": packet_evidence_id,
            "terminal_readiness": terminal_readiness,
        },
    )
    return {"changed": True, "from_status": target["status"], "to_status": "done"}


def _same_terminal_readiness_snapshot(
    expected: dict[str, Any] | None,
    current: dict[str, Any],
) -> bool:
    if not isinstance(expected, dict):
        return False
    expected_evaluation = expected.get("evaluation")
    current_evaluation = current.get("evaluation")
    if not isinstance(expected_evaluation, dict) or not isinstance(
        current_evaluation,
        dict,
    ):
        return False
    expected_transition = expected.get("transition")
    current_transition = current.get("transition")
    return (
        expected.get("terminal_allowed") is True
        and current.get("terminal_allowed") is True
        and expected_transition == current_transition
        and expected_evaluation.get("evaluated_through_event_sequence")
        == current_evaluation.get("evaluated_through_event_sequence")
        and expected_evaluation.get("evaluated_through_event_id")
        == current_evaluation.get("evaluated_through_event_id")
        and expected_evaluation.get("input_sha256")
        == current_evaluation.get("input_sha256")
    )


def _finish_check_policy(
    commands: list[dict[str, Any]],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
) -> dict[str, Any]:
    return {
        "contract_version": "finish-check-policy/v1",
        "commands": [
            {
                "id": command.get("step_id"),
                "scope": command.get("scope"),
                "config_key": command.get("config_key"),
                "kind": command.get("kind"),
                "argv": [str(part) for part in command.get("argv", [])],
                "role_bindings": list(command.get("role_bindings", [])),
            }
            for command in commands
        ],
        "declared_output_patterns": list(FINISH_DECLARED_OUTPUT_PATTERNS),
        "timeout_seconds": timeout_seconds,
        "max_output_bytes": max_output_bytes,
        "stability": {
            "minimum_consecutive_passes": (
                FINISH_STABILITY_MINIMUM_CONSECUTIVE_PASSES
            ),
            "maximum_attempts": FINISH_STABILITY_MAXIMUM_ATTEMPTS,
            "required_strata": ["cold", "warm"],
        },
    }


def _attach_finish_check_contracts(
    command: dict[str, Any],
    *,
    paths: ProjectPaths,
    target: dict[str, Any],
    input_manifest: dict[str, Any],
    finish_policy: dict[str, Any],
    timeout_seconds: int,
    max_output_bytes: int,
) -> None:
    stability_stratum = "cold"
    identity = build_verification_attempt_identity(
        input_manifest=input_manifest,
        command=command,
        finish_policy=finish_policy,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        stability_stratum=stability_stratum,
    )
    provisional = build_finish_check_result(
        command,
        evidence_id="E-0000",
        attempt_identity=identity,
        stability_evaluation={},
    )
    execution_identity_sha256 = str(identity["execution_identity_sha256"])
    history = load_compatible_check_history(
        paths,
        target_type=str(target["type"]),
        target_id=str(target["id"]),
        execution_identity_sha256=execution_identity_sha256,
        maximum_attempts=FINISH_STABILITY_MAXIMUM_ATTEMPTS,
    )
    current_attempt = {
        "attempt_identity": identity,
        "assertion_result": provisional["assertion_result"],
        "stratum": stability_stratum,
    }
    stability = evaluate_stability(
        [
            *(row["attempt"] for row in history["compatible"]),
            current_attempt,
        ],
        minimum_consecutive_passes=FINISH_STABILITY_MINIMUM_CONSECUTIVE_PASSES,
        maximum_attempts=FINISH_STABILITY_MAXIMUM_ATTEMPTS,
    )
    command["attempt_identity"] = identity
    command["stability_stratum"] = stability_stratum
    command["stability_evaluation"] = stability
    role_bindings = list(command.get("role_bindings", []))
    command["reuse"] = {
        "contract_version": CHECK_RESULT_REUSE_CONTRACT_VERSION,
        "execution_identity_sha256": execution_identity_sha256,
        "execution_source": "fresh",
        "role_bindings": role_bindings,
        "reused_role_count": max(0, len(role_bindings) - 1),
        "compatible_history": [
            row["public"] for row in history["compatible"]
        ],
        "history_rejections": history["rejections"],
        "history_candidate_count": history["candidate_count"],
        "history_scan_limit": history["scan_limit"],
    }


def _check_result(command: dict[str, Any], *, evidence_id: str) -> dict[str, Any]:
    return build_finish_check_result(
        command,
        evidence_id=evidence_id,
        attempt_identity=command["attempt_identity"],
        stability_evaluation=command["stability_evaluation"],
    )


def _apply_observability_verification(
    command: dict[str, Any], verification: Mapping[str, Any]
) -> None:
    if verification.get("ok") is True:
        return
    failure_kind = str(
        verification.get("failure_kind") or "artifact_integrity_failed"
    )
    observation = command.get("observability")
    if not isinstance(observation, Mapping):
        observation = {}
    failed_observation = json.loads(json.dumps(dict(observation), ensure_ascii=False))
    failed_observation.update(
        {
            "eligible": False,
            "status": "unavailable",
            "failure_kind": failure_kind,
            "verification": {
                "ok": False,
                "failure_kind": failure_kind,
                "issues": [
                    str(issue)
                    for issue in verification.get("issues", [])
                    if isinstance(issue, (str, int, float, bool))
                ],
            },
        }
    )
    command["observability"] = failed_observation
    command["status"] = "failed"
    command["observability_failure_kind"] = failure_kind
    if not command.get("failure_kind"):
        command["failure_kind"] = failure_kind


def _verify_command_observability(
    command: dict[str, Any], *, root: Path
) -> dict[str, Any]:
    observation = command.get("observability")
    if not isinstance(observation, Mapping):
        verification = {
            "ok": False,
            "failure_kind": "observer_unavailable",
            "issues": ["observability_missing"],
        }
    else:
        summary_value = observation.get("summary_path")
        if not isinstance(summary_value, str) or not summary_value:
            verification = {
                "ok": False,
                "failure_kind": "artifact_integrity_failed",
                "issues": ["summary_path_missing"],
            }
        else:
            summary_path = Path(summary_value)
            if not summary_path.is_absolute():
                summary_path = root / summary_path
            verification = verify_runner_observability(
                summary_path,
                root=root,
                allow_pending_result=_has_pending_observability_result(observation),
            )
    command["observability_verification"] = verification
    _apply_observability_verification(command, verification)
    return verification


def _has_persisted_observability_paths(observation: Any) -> bool:
    return isinstance(observation, Mapping) and all(
        isinstance(observation.get(key), str) and bool(observation.get(key))
        for key in ("summary_path", "events_path")
    )


def _has_pending_observability_result(observation: Mapping[str, Any]) -> bool:
    artifacts = observation.get("artifacts")
    result = artifacts.get("result") if isinstance(artifacts, Mapping) else None
    return isinstance(result, Mapping) and result.get("path") is None and result.get(
        "sha256"
    ) is None


def _check_result_anchors(
    check_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "evidence_id": str(row["evidence_id"]),
            "sha256": str(row["artifact_sha256"]),
        }
        for row in check_rows
    ]


def _matching_completion_packet(paths: ProjectPaths, *, target: dict[str, Any], repository: dict[str, Any]) -> dict[str, Any] | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT evidence.id, evidence.path FROM evidence
            JOIN evidence_links ON evidence_links.evidence_id = evidence.id
            WHERE evidence.type = ? AND evidence_links.target_type = ?
              AND evidence_links.target_id = ? AND evidence_links.link_role = ?
            ORDER BY evidence.created_at DESC, evidence.id DESC LIMIT 1
            """,
            (COMPLETION_PACKET_EVIDENCE_TYPE, target["type"], target["id"], COMPLETION_PACKET_LINK_ROLE),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    path = paths.root / str(row["path"])
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if packet.get("repository") != repository:
        return None
    return {"packet_id": packet["packet_id"], "evidence_id": str(row["id"]), "path": str(row["path"]), "outcome": packet["outcome"]}


def _target_is_terminal(paths: ProjectPaths, target: dict[str, Any]) -> bool:
    conn = connect(paths.db_path)
    try:
        table = "tasks" if target["type"] == "task" else "goals"
        row = conn.execute(f"SELECT status FROM {table} WHERE id = ?", (target["id"],)).fetchone()
    finally:
        conn.close()
    return row is not None and str(row["status"]) in {"done", "closed", "cancelled", "waived"}


def _stage_check_dir(paths: ProjectPaths) -> Path:
    tmp_dir = paths.loop_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="finish-checks-", dir=tmp_dir))


def _snapshot_identity(value: dict[str, Any]) -> tuple[Any, ...]:
    repository = value.get("repository") or value["packet_repository"]
    changes = value.get("changes", [])
    return (repository["base_revision"], repository["head_revision"], repository["diff_sha256"], repository["dirty"], json.dumps(changes, sort_keys=True))


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": manifest["contract_version"],
        "manifest_sha256": manifest["manifest_sha256"],
        "ok": bool(manifest["ok"]),
        "entry_count": len(manifest["entries"]),
        "error_count": len(manifest["errors"]),
        "errors": manifest["errors"],
    }


def _public_check_plan(command: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": command["id"], "config_key": str(command["raw_command"]).removeprefix("project.commands."),
        "command": command["resolved_command"], "safe_to_run": bool(command["safe_to_run"]),
        "blocked_reason": command["blocked_reason"],
    }
    role_bindings = list(command.get("role_bindings", []))
    if len(role_bindings) > 1:
        result["role_bindings"] = role_bindings
        result["reused_role_count"] = len(role_bindings) - 1
    return result


def _coalesce_finish_checks(
    commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for command in commands:
        config_key = _finish_config_key(command)
        command["config_key"] = config_key
        command["scope"] = "finish_checks"
        binding = {
            "check_id": str(command["id"]),
            "config_key": config_key,
        }
        argv = tuple(str(part) for part in command.get("argv", []))
        key = (
            str(command.get("scope") or ""),
            str(command.get("kind") or ""),
            argv or (f"unresolved:{command.get('resolved_command')}",),
        )
        primary = unique.get(key)
        if primary is None:
            command["role_bindings"] = [binding]
            unique[key] = command
            ordered.append(command)
        else:
            primary["role_bindings"].append(binding)
    return ordered


def _finish_config_key(command: dict[str, Any]) -> str:
    return str(command.get("raw_command") or "").removeprefix(
        "project.commands."
    )
