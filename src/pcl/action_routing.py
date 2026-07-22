from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

from .checkpoints import checkpoint_status
from .contracts.completion_packet import validate_completion_packet
from .db import connect
from .dispatch import expired_lease_job_ids
from .errors import InvalidInputError
from .finish_recovery import completion_packet_timeout_action
from .guards import require_initialized
from .lifecycle import ACTIVE_JOB_STATUSES, ACTIVE_RUN_STATUSES, TERMINAL_JOB_STATUSES
from .links import linked_decisions_for_escalation
from .locales import HUMAN_GATE_JA
from .paths import ProjectPaths
from .project_config import finish_check_configuration
from .target_resolver import TaskGoalTargetNotFoundError, resolve_existing_task_goal
from .workflow_proposals import next_reviewable_workflow_proposal

from .command_domain import loop_status

TASK_ACTIONABLE_STATUSES = {"todo", "ready"}
TASK_COMPLETED_DEPENDENCY_STATUSES = {"done", "cancelled", "waived"}


def build_next_action(
    *,
    action_type: str,
    command: str | None,
    reason: str,
    target,
    priority: int,
    blocking: bool,
    requires_human: bool,
    safe_to_run: bool,
    expected_after: str,
) -> dict:
    run_policy = _run_policy(
        blocking=blocking,
        requires_human=requires_human,
        safe_to_run=safe_to_run,
    )
    action = {
        "type": action_type,
        "command": command,
        "reason": reason,
        "target": target,
        "priority": priority,
        "blocking": blocking,
        "requires_human": requires_human,
        "safe_to_run": safe_to_run,
        "expected_after": expected_after,
        "run_policy": run_policy,
        "human_guidance": _human_guidance(
            run_policy=run_policy,
            blocking=blocking,
        ),
    }
    if requires_human:
        action.update(
            human_decision_action_fields(
                action_type=action_type,
                command=command,
                reason=reason,
                target=target,
                blocking=blocking,
            )
        )
    return action


def human_decision_action_fields(
    *,
    action_type: str,
    command: str,
    reason: str,
    target: object,
    blocking: bool,
) -> dict:
    return {
        "why_blocked": _why_blocked(reason=reason, blocking=blocking),
        "options": _human_next_action_options(
            action_type=action_type,
            command=command,
            target=target,
        ),
        "recommendation": _action_recommendation(action_type=action_type, command=command, target=target),
        "recommendation_reason": reason,
        "related_evidence_paths": [],
        "receipt_paths": [],
        "human_guidance_ja": _human_guidance_ja(
            action_type=action_type,
            blocking=blocking,
            options=_human_next_action_options(
                action_type=action_type,
                command=command,
                target=target,
            ),
        ),
    }


def _human_guidance_ja(*, action_type: str, blocking: bool, options: list[dict]) -> dict:
    why = HUMAN_GATE_JA["why_blocked"].get(action_type, HUMAN_GATE_JA["why_blocked"]["_default"])
    if blocking:
        why = HUMAN_GATE_JA["blocking_prefix"] + why
    check = HUMAN_GATE_JA["check"].get(action_type, HUMAN_GATE_JA["check"]["_default"])
    labels = HUMAN_GATE_JA["option_labels"]
    next_options = [labels.get(str(option.get("label")), str(option.get("label"))) for option in options]
    return {
        "why_blocked": why,
        "check": list(check),
        "next_options": next_options,
    }


def decision_options(decision_id: str) -> list[dict[str, str]]:
    return [
        _decision_option(
            label="Approve",
            command=(
                f"pcl decision resolve {decision_id} --selected-option 'Approve recommended path' "
                "--reason '<why this is acceptable>'"
            ),
            why_safe="Uses pcl to record the human choice and close the open decision.",
            risk_if_run="The chosen option becomes durable loop state and may unblock follow-up work.",
        ),
        _decision_option(
            label="Reject",
            command=(
                f"pcl decision resolve {decision_id} --selected-option 'Reject recommended path' "
                "--reason '<why this should not proceed>'"
            ),
            why_safe="Uses pcl to record a durable rejection instead of leaving the decision implicit.",
            risk_if_run="The rejection closes this decision; a new decision may be needed for an alternate path.",
        ),
        _decision_option(
            label="Hold",
            command=f"pcl decision waive {decision_id} --reason '<why this no longer blocks safe continuation>'",
            why_safe="Uses pcl to mark the decision as waived with a required reason.",
            risk_if_run="Waiving removes this item from the blocking queue without selecting an implementation path.",
        ),
        _decision_option(
            label="Request more evidence",
            command=f"pcl decision read {decision_id} --json",
            why_safe="Read-only command; it does not mutate project-loop state.",
            risk_if_run="The loop remains blocked until the decision is resolved or waived.",
        ),
    ]


def escalation_options(
    escalation_id: str,
    *,
    linked_decision_ids: list[str] | None = None,
    workflow_run_id: str = "",
) -> list[dict[str, str]]:
    linked_decision_ids = linked_decision_ids or []
    if linked_decision_ids:
        approve_command = (
            f"pcl escalation resolve {escalation_id} --decision {linked_decision_ids[0]} "
            "--summary '<summary>'"
        )
        approve_why = "Uses pcl to resolve the escalation while preserving its linked decision reference."
        approve_risk = "The escalation closes; any remaining disagreement must be captured in a new decision."
    else:
        approve_command = (
            f"pcl decision open --escalation {escalation_id} "
            f"--question 'Record the human decision for {escalation_id}' "
            "--recommendation 'Choose the safe next step'"
        )
        approve_why = "Uses pcl to create the durable decision needed before resolving this escalation."
        approve_risk = "The escalation remains open until the new decision is resolved and linked back."

    evidence_command = f"pcl report run {workflow_run_id}" if workflow_run_id else f"pcl escalation read {escalation_id} --json"
    return [
        _decision_option(
            label="Approve",
            command=approve_command,
            why_safe=approve_why,
            risk_if_run=approve_risk,
        ),
        _decision_option(
            label="Reject",
            command=f"pcl escalation cancel {escalation_id} --summary '<why this should not proceed>'",
            why_safe="Uses pcl to close the escalation as cancelled with an explicit summary.",
            risk_if_run="Cancelling removes the escalation from the human queue without resolving linked work.",
        ),
        _decision_option(
            label="Hold",
            command=f"pcl escalation read {escalation_id} --json",
            why_safe="Read-only command; it keeps the escalation open while reviewing context.",
            risk_if_run="The blocking escalation remains open and will continue to appear as the next action.",
        ),
        _decision_option(
            label="Request more evidence",
            command=evidence_command,
            why_safe="Read-only review command; it does not mutate project-loop state.",
            risk_if_run="The escalation remains unresolved until a human records the outcome.",
        ),
    ]


def verification_options(workflow_run_id: str) -> list[dict[str, str]]:
    return [
        _decision_option(
            label="Approve",
            command=(
                f"pcl verification record --run {workflow_run_id} --result approved "
                "--reason '<why the run is acceptable>'"
            ),
            why_safe="Uses pcl to record an explicit verification result for the run.",
            risk_if_run="Approval may allow the workflow to complete if other terminal conditions are met.",
        ),
        _decision_option(
            label="Reject",
            command=(
                f"pcl verification record --run {workflow_run_id} --result rejected "
                "--reason '<why the run should not pass>'"
            ),
            why_safe="Uses pcl to record a durable rejection with a required reason.",
            risk_if_run="The run remains failed or blocked until follow-up repair work is routed.",
        ),
        _decision_option(
            label="Hold",
            command=(
                f"pcl verification record --run {workflow_run_id} --result inconclusive "
                "--reason '<why the run cannot be decided yet>'"
            ),
            why_safe="Uses pcl to record that verification is deliberately inconclusive.",
            risk_if_run="The workflow remains unresolved and may need another verification or escalation.",
        ),
        _decision_option(
            label="Request more evidence",
            command=f"pcl report run {workflow_run_id}",
            why_safe="Read-only report command; it gathers run context without changing state.",
            risk_if_run="The human-required state remains until a verification or escalation is recorded.",
        ),
    ]


def generic_human_options(command: str, *, evidence_command: str = "pcl validate --json") -> list[dict[str, str]]:
    return [
        _decision_option(
            label="Approve",
            command=command,
            why_safe="Uses the recommended pcl command instead of direct state mutation.",
            risk_if_run="The command may change durable loop state; review the target before running it.",
        ),
        _decision_option(
            label="Reject",
            command="pcl next --json",
            why_safe="Read-only command; it leaves durable loop state unchanged.",
            risk_if_run="No rejection is recorded, so the same recommendation may remain next.",
        ),
        _decision_option(
            label="Hold",
            command="pcl next --json",
            why_safe="Read-only command; it keeps the current state intact.",
            risk_if_run="The loop may remain stopped until a human records a more durable outcome.",
        ),
        _decision_option(
            label="Request more evidence",
            command=evidence_command,
            why_safe="Read-only review command; it does not mutate project-loop state.",
            risk_if_run="The decision remains pending until an operator runs a state-changing pcl command.",
        ),
    ]


def _human_next_action_options(
    *,
    action_type: str,
    command: str,
    target: object,
) -> list[dict[str, str]]:
    target_dict = target if isinstance(target, dict) else {}
    target_id = str(target_dict.get("id") or "")
    if action_type == "resolve_decision" and target_id:
        return decision_options(target_id)
    if action_type == "resolve_escalation" and target_id:
        return escalation_options(
            target_id,
            linked_decision_ids=[str(item) for item in target_dict.get("linked_decision_ids", [])],
            workflow_run_id=str(target_dict.get("workflow_run_id") or ""),
        )
    if action_type in {"open_escalation", "record_verification"}:
        workflow_run_id = str(target_dict.get("id") or target_dict.get("workflow_run_id") or "")
        if workflow_run_id:
            return verification_options(workflow_run_id)
    evidence_command = _evidence_command_for_target(target_dict)
    return generic_human_options(command, evidence_command=evidence_command)


def _evidence_command_for_target(target: dict) -> str:
    workflow_run_id = str(target.get("workflow_run_id") or "")
    if not workflow_run_id and str(target.get("id") or "").startswith("WR-"):
        workflow_run_id = str(target.get("id"))
    if workflow_run_id:
        return f"pcl report run {workflow_run_id}"
    return "pcl validate --json"


def _action_recommendation(*, action_type: str, command: str, target: object) -> str:
    if isinstance(target, dict) and str(target.get("recommendation") or "").strip():
        return str(target["recommendation"]).strip()
    if action_type == "resolve_decision":
        return "Resolve or waive the open decision after reviewing the options."
    if action_type == "resolve_escalation":
        return "Record the human outcome for the open escalation."
    if action_type in {"open_escalation", "record_verification"}:
        return "Choose a verification outcome or open an escalation with the missing evidence."
    return f"Run or decline the recommended command: {command}"


def _why_blocked(*, reason: str, blocking: bool) -> str:
    if blocking:
        return reason
    return "Human confirmation is required before this recommended state transition should run."


def _decision_option(*, label: str, command: str, why_safe: str, risk_if_run: str) -> dict[str, str]:
    return {
        "label": label,
        "command": command,
        "why_safe": why_safe,
        "risk_if_run": risk_if_run,
    }


def _run_policy(*, blocking: bool, requires_human: bool, safe_to_run: bool) -> str:
    if safe_to_run:
        return "agent_safe"
    if requires_human:
        return "human_decision"
    if blocking:
        return "manual_resolution"
    return "manual_state_transition"


def _human_guidance(*, run_policy: str, blocking: bool) -> str:
    prefix = "Normal loop continuation should wait. " if blocking else ""
    if run_policy == "agent_safe":
        return prefix + "An agent or automation may run this command in the current project context."
    if run_policy == "human_decision":
        return prefix + "A human should choose or confirm this state transition before the command is run."
    if run_policy == "manual_resolution":
        return prefix + "Resolve the blocking state deliberately; do not auto-run this command blindly."
    return prefix + "This mutates durable loop state; run it deliberately after reviewing the recommendation."


def _idle_next_action() -> dict:
    return {
        "type": "idle",
        "command": None,
        "reason": (
            "No active work or pending human decision exists; pass explicit intent "
            "to `pcl start` when work is requested."
        ),
        "target": None,
        "priority": 70,
        "blocking": False,
        "requires_human": False,
        "safe_to_run": False,
        "expected_after": (
            "No state changes until explicit intent is passed to `pcl start \"<intent>\"`."
        ),
        "run_policy": "idle",
        "human_guidance": (
            "No durable action is pending. When explicit user intent is available, "
            "pass it literally to `pcl start \"<intent>\"`."
        ),
    }


def next_action(paths: ProjectPaths, *, target: str | None = None) -> dict:
    if target is not None:
        return _targeted_next_action(paths, target_id=target)

    status = loop_status(paths)
    escalation = _open_escalation_next_action(paths)
    if escalation is not None:
        return escalation
    decision = _open_decision_next_action(paths)
    if decision is not None:
        return decision
    needs_human = _needs_human_escalation_next_action(paths)
    if needs_human is not None:
        return needs_human
    unfinished_executor = _unfinished_executor_next_action(paths)
    if unfinished_executor is not None:
        return unfinished_executor
    expired_leases = _expired_lease_next_action(paths)
    if expired_leases is not None:
        return expired_leases
    active = _active_workflow_next_action(paths)
    if active is not None:
        return active
    retry_executor = _failed_executor_retry_next_action(paths)
    if retry_executor is not None:
        return retry_executor
    if status["open_defects"]:
        defect = status["open_defects"][0]
        return _defect_next_action(defect)
    proposal = _workflow_proposal_review_next_action(paths)
    if proposal is not None:
        return proposal
    checkpoint = _checkpoint_review_next_action(paths)
    if checkpoint is not None:
        return checkpoint
    timeout_recovery = _finish_timeout_recovery_next_action(paths)
    if timeout_recovery is not None:
        return timeout_recovery
    target_selection = _ambiguous_next_target_action(paths)
    if target_selection is not None:
        return target_selection
    task = _task_next_action(paths)
    if task is not None:
        return task
    terminal_goal = _terminal_direct_goal_next_action(paths)
    if terminal_goal is not None:
        return terminal_goal
    passing_feature = _passing_feature_next_action(paths)
    if passing_feature is not None:
        return passing_feature
    if status["open_goals"]:
        goal = status["open_goals"][0]
        return _continue_goal_next_action(goal)
    uncovered_feature = _uncovered_feature_next_action(paths)
    if uncovered_feature is not None:
        return uncovered_feature
    return _idle_next_action()


def _targeted_next_action(paths: ProjectPaths, *, target_id: str) -> dict:
    target = _resolve_next_target(paths, target_id=target_id)
    binding = {
        "target_type": target["type"],
        "target_id": target["id"],
        "source": "explicit",
    }

    for detector in (
        _open_escalation_next_action,
        _open_decision_next_action,
        _needs_human_escalation_next_action,
    ):
        action = detector(paths)
        if action is not None:
            return _bind_next_action(action, binding=binding, routing_scope="project_gate")

    expired_leases = _expired_lease_next_action(paths)
    if expired_leases is not None:
        return _bind_next_action(
            expired_leases,
            binding=binding,
            routing_scope="project_gate",
        )

    if target["status"] in {"done", "closed", "cancelled", "waived"}:
        return _bind_next_action(
            _terminal_next_target_action(target),
            binding=binding,
            routing_scope="target",
        )

    goal_id = target["id"] if target["type"] == "goal" else target.get("related_goal_id")
    if goal_id:
        unfinished_executor = _unfinished_executor_next_action(paths, goal_id=str(goal_id))
        if unfinished_executor is not None:
            return _bind_next_action(
                unfinished_executor,
                binding=binding,
                routing_scope="target",
            )

    if goal_id:
        active = _active_workflow_next_action(paths, goal_id=str(goal_id))
        if active is not None:
            return _bind_next_action(active, binding=binding, routing_scope="target")
        retry = _failed_executor_retry_next_action(paths, goal_id=str(goal_id))
        if retry is not None:
            return _bind_next_action(retry, binding=binding, routing_scope="target")

    if target["type"] == "task":
        action = _explicit_task_next_action(paths, task=target)
        return _bind_next_action(action, binding=binding, routing_scope="target")

    terminal_goal = _terminal_direct_goal_next_action(paths, goal_id=target["id"])
    if terminal_goal is not None:
        return _bind_next_action(terminal_goal, binding=binding, routing_scope="target")
    task = _task_next_action(paths, goal_id=target["id"])
    if task is not None:
        return _bind_next_action(task, binding=binding, routing_scope="target")
    if target["status"] == "blocked":
        action = build_next_action(
            action_type="inspect_blocked_goal",
            command=f"pcl task list --goal {target['id']} --json",
            reason="The explicitly selected Goal is blocked; inspect its linked Tasks before continuing.",
            target=target,
            priority=59,
            blocking=True,
            requires_human=False,
            safe_to_run=True,
            expected_after="The blocking Task or missing prerequisite is identified.",
        )
    else:
        action = _continue_goal_next_action(target)
    return _bind_next_action(action, binding=binding, routing_scope="target")


def _resolve_next_target(paths: ProjectPaths, *, target_id: str) -> dict[str, Any]:
    require_initialized(paths)
    conn = connect(paths.db_path)
    try:
        try:
            resolved = resolve_existing_task_goal(conn, target_id)
        except TaskGoalTargetNotFoundError as exc:
            raise InvalidInputError(
                f"Next target does not exist: {target_id}",
                details={"target": target_id, "target_type": exc.target_type},
            ) from exc

        row = resolved.row
        if resolved.type == "task":
            related_goal = conn.execute(
                "SELECT status FROM goals WHERE id = ?",
                (row["related_goal_id"],),
            ).fetchone()
            return {
                "type": "task",
                **{
                    key: row[key]
                    for key in (
                        "id",
                        "title",
                        "description",
                        "status",
                        "priority",
                        "owner",
                        "risk",
                        "effort",
                        "related_goal_id",
                        "related_feature_id",
                        "related_defect_id",
                        "created_at",
                        "updated_at",
                    )
                },
                "related_goal_status": related_goal["status"] if related_goal else None,
            }
        return {
            "type": "goal",
            **{
                key: row[key]
                for key in ("id", "title", "status", "created_at", "updated_at")
            },
        }
    finally:
        conn.close()


def _bind_next_action(action: dict, *, binding: dict, routing_scope: str) -> dict:
    return {
        **action,
        "target_binding": dict(binding),
        "routing_scope": routing_scope,
    }


def _terminal_next_target_action(target: dict) -> dict:
    return build_next_action(
        action_type="target_terminal",
        command=None,
        reason=(
            f"The explicitly selected {target['type']} {target['id']} is already "
            f"terminal ({target['status']})."
        ),
        target=target,
        priority=70,
        blocking=False,
        requires_human=False,
        safe_to_run=False,
        expected_after="No state changes; start or select another target when new work is requested.",
    )


def _explicit_task_next_action(paths: ProjectPaths, *, task: dict) -> dict:
    conn = connect(paths.db_path)
    try:
        enriched = _task_next_action_target(conn, dict(task))
    finally:
        conn.close()
    task_id = str(enriched["id"])
    if enriched["status"] == "blocked":
        return build_next_action(
            action_type="inspect_blocked_task",
            command=f"pcl task read {task_id} --json",
            reason="The explicitly selected Task is blocked; inspect its dependencies before continuing.",
            target=enriched,
            priority=59,
            blocking=True,
            requires_human=False,
            safe_to_run=True,
            expected_after=f"The blocker or unmet dependency for Task {task_id} is identified.",
        )
    reason = (
        "The explicitly selected Task is already in progress."
        if enriched["status"] == "in_progress"
        else "The explicitly selected Task is ready for focused work."
    )
    return build_next_action(
        action_type="work_on_task",
        command=f"pcl context pack --task {task_id} --json",
        reason=reason,
        target=enriched,
        priority=59,
        blocking=False,
        requires_human=False,
        safe_to_run=True,
        expected_after=f"The task context pack is reviewed and Task {task_id} advances toward done.",
    )


def _ambiguous_next_target_action(paths: ProjectPaths) -> dict | None:
    candidates = _ambiguous_next_target_candidates(paths)
    if not candidates:
        return None
    action = build_next_action(
        action_type="select_target",
        command=None,
        reason=(
            "Actionable work spans multiple Goals; select the Task or Goal that matches "
            "the current intent instead of following an implicit database order."
        ),
        target={
            "candidate_level": candidates[0]["type"],
            "candidates": candidates,
            "selection_command": "pcl next --target <T-XXXX|G-XXXX> --json",
        },
        priority=59,
        blocking=False,
        requires_human=False,
        safe_to_run=False,
        expected_after="A target-bound read-only next action is returned for the selected ID.",
    )
    action["run_policy"] = "target_selection"
    action["human_guidance"] = (
        "Choose the candidate that matches current intent, then rerun pcl next with --target."
    )
    return action


def _ambiguous_next_target_candidates(paths: ProjectPaths) -> list[dict[str, Any]]:
    conn = connect(paths.db_path)
    try:
        in_progress = _next_task_candidates(conn, statuses=("in_progress",))
        if in_progress:
            if len({row["related_goal_id"] for row in in_progress}) > 1:
                return _one_next_candidate_per_goal(in_progress)
            return []

        actionable = _next_actionable_task_candidates(conn)
        if len({row["related_goal_id"] for row in actionable}) > 1:
            return _one_next_candidate_per_goal(actionable)

        if actionable:
            return []
        goals = conn.execute(
            """
            SELECT id, title, status
            FROM goals
            WHERE status IN ('open', 'active', 'blocked')
            ORDER BY created_at, id
            """
        ).fetchall()
        if len(goals) > 1:
            return [{"type": "goal", **dict(row)} for row in goals]
        return []
    finally:
        conn.close()


def _next_task_candidate(row) -> dict[str, Any]:
    return {
        "type": "task",
        "id": str(row["id"]),
        "title": str(row["title"]),
        "status": str(row["status"]),
        "related_goal_id": str(row["related_goal_id"]),
    }


def _one_next_candidate_per_goal(rows) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_goal_ids: set[str] = set()
    for row in rows:
        goal_id = str(row["related_goal_id"])
        if goal_id in seen_goal_ids:
            continue
        candidates.append(_next_task_candidate(row))
        seen_goal_ids.add(goal_id)
    return candidates


def _finish_timeout_recovery_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT evidence.id, evidence.path, evidence.created_at,
                   evidence_links.target_type, evidence_links.target_id
            FROM evidence_links
            JOIN evidence ON evidence.id = evidence_links.evidence_id
            WHERE evidence.type = 'completion_packet'
              AND evidence_links.link_role = 'completion_packet'
              AND evidence_links.target_type IN ('goal', 'task')
            ORDER BY evidence.created_at DESC, evidence.id DESC
            """
        ).fetchall()
        seen_targets: set[tuple[str, str]] = set()
        for row in rows:
            target_type = str(row["target_type"])
            target_id = str(row["target_id"])
            target_key = (target_type, target_id)
            if target_key in seen_targets:
                continue
            table = "goals" if target_type == "goal" else "tasks"
            target_row = conn.execute(
                f"SELECT status FROM {table} WHERE id = ?",
                (target_id,),
            ).fetchone()
            if target_row is None or str(target_row["status"]) in {
                "closed",
                "done",
                "cancelled",
                "waived",
            }:
                continue
            path = paths.root / str(row["path"])
            try:
                packet = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, JSONDecodeError):
                continue
            if not validate_completion_packet(packet).ok:
                continue
            seen_targets.add(target_key)
            action = completion_packet_timeout_action(packet)
            if action is None:
                continue
            retrying = action["type"] == "retry_finish_timeout"
            return build_next_action(
                action_type=action["type"],
                command=action["command"],
                reason=action["reason"],
                target={
                    "id": target_id,
                    "type": target_type,
                    "status": str(target_row["status"]),
                    "completion_packet_evidence_id": str(row["id"]),
                },
                priority=45,
                blocking=not retrying,
                requires_human=False,
                safe_to_run=True,
                expected_after=(
                    "Configured finish checks rerun with the bounded timeout and emit a new packet."
                    if retrying
                    else "The agent inspects timeout Evidence before choosing a different corrective action."
                ),
            )
    finally:
        conn.close()
    return None


def _terminal_direct_goal_next_action(
    paths: ProjectPaths,
    *,
    goal_id: str | None = None,
) -> dict | None:
    conn = connect(paths.db_path)
    try:
        goal_filter = "AND goals.id = ?" if goal_id else ""
        goal = conn.execute(
            f"""
            SELECT goals.id, goals.title, goals.status
            FROM goals
            WHERE goals.status IN ('open', 'active')
              {goal_filter}
              AND EXISTS (SELECT 1 FROM tasks WHERE tasks.related_goal_id = goals.id)
              AND NOT EXISTS (
                SELECT 1 FROM tasks
                WHERE tasks.related_goal_id = goals.id
                  AND tasks.status NOT IN ('done', 'cancelled', 'waived')
              )
              AND NOT EXISTS (
                SELECT 1 FROM workflow_runs WHERE workflow_runs.goal_id = goals.id
              )
              AND NOT EXISTS (
                SELECT 1
                FROM tasks
                JOIN features ON features.id = tasks.related_feature_id
                WHERE tasks.related_goal_id = goals.id
                  AND features.status NOT IN ('done', 'waived')
              )
              AND NOT EXISTS (
                SELECT 1
                FROM tasks
                JOIN test_cases ON test_cases.feature_id = tasks.related_feature_id
                WHERE tasks.related_goal_id = goals.id
                  AND test_cases.status NOT IN ('passing', 'waived')
              )
            ORDER BY goals.created_at, goals.id
            LIMIT 1
            """,
            (goal_id,) if goal_id else (),
        ).fetchone()
    finally:
        conn.close()
    if goal is None:
        return None
    target = dict(goal)
    configuration = finish_check_configuration(paths.root)
    target["finish_checks"] = configuration
    if not configuration["configured"]:
        return build_next_action(
            action_type="configure_finish_checks",
            command="pcl doctor --json",
            reason=(
                "All linked direct-route Tasks are terminal, but no enabled finish check is "
                "configured. Configure verification before emitting a completion packet."
            ),
            target=target,
            priority=57,
            blocking=True,
            requires_human=False,
            safe_to_run=True,
            expected_after=(
                "pcl.yaml contains at least one enabled finish check and `pcl finish --emit-packet` "
                "can distinguish executed verification from configuration setup."
            ),
        )
    return build_next_action(
        action_type="emit_completion_packet",
        command=f"pcl finish --emit-packet --goal {goal['id']} --json",
        reason=(
            "All linked direct-route Tasks and their Feature/Test work are terminal; emit the "
            "goal-bound completion packet instead of starting feature_coverage."
        ),
        target=target,
        priority=57,
        blocking=False,
        requires_human=False,
        safe_to_run=True,
        expected_after="Configured checks run and a goal-bound completion packet records the result.",
    )



def _continue_goal_next_action(goal: dict) -> dict:
    return build_next_action(
        action_type="continue_goal",
        command=f"pcl loop run feature_coverage --goal {goal['id']}",
        reason="There is an open goal and no open defects.",
        target=goal,
        priority=60,
        blocking=False,
        requires_human=False,
        safe_to_run=False,
        expected_after="A workflow run exists for the open goal.",
    )


def _passing_feature_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, name, surface, description, status, confidence, created_at, updated_at
            FROM features
            WHERE status = 'passing'
            ORDER BY created_at, id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        feature = dict(row)
        tests = conn.execute(
            """
            SELECT id, status, evidence_id
            FROM test_cases
            WHERE feature_id = ? AND status != 'waived'
            ORDER BY id
            """,
            (feature["id"],),
        ).fetchall()
        blockers: list[dict[str, Any]] = []
        for test in tests:
            if test["status"] != "passing":
                blockers.append(
                    {
                        "code": "test_not_passing",
                        "test_case_id": str(test["id"]),
                        "status": str(test["status"]),
                    }
                )
                continue
            event = conn.execute(
                """
                SELECT payload_json
                FROM events
                WHERE event_type IN ('test_case_passed', 'test_case_reverified')
                  AND entity_type = 'test_case'
                  AND entity_id = ?
                ORDER BY sequence DESC, id DESC
                LIMIT 1
                """,
                (test["id"],),
            ).fetchone()
            payload = _parse_event_payload(str(event["payload_json"] or "{}")) if event else {}
            evaluation = payload.get("completion_evaluation")
            if not isinstance(evaluation, dict):
                blockers.append(
                    {
                        "code": "completion_policy_receipt_missing",
                        "test_case_id": str(test["id"]),
                        "evidence_id": str(test["evidence_id"] or ""),
                        "required_artifacts": ["evidence-set/v1", "completion-policy/v1"],
                    }
                )
            elif (
                evaluation.get("status") != "passed"
                or evaluation.get("evidence_set_id") != str(test["evidence_id"] or "")
            ):
                blockers.append(
                    {
                        "code": "completion_policy_not_passed",
                        "test_case_id": str(test["id"]),
                        "evidence_id": str(test["evidence_id"] or ""),
                        "status": str(evaluation.get("status") or "unknown"),
                        "findings": evaluation.get("findings", []),
                    }
                )
        if not tests:
            blockers.append(
                {
                    "code": "completion_tests_missing",
                    "test_case_id": None,
                    "required_artifacts": ["evidence-set/v1", "completion-policy/v1"],
                }
            )
        feature["completion_status"] = "blocked" if blockers else "ready_for_explicit_done_review"
        feature["completion_blockers"] = blockers
        blocker_evidence_id = next(
            (
                str(item["evidence_id"])
                for item in blockers
                if isinstance(item.get("evidence_id"), str) and item["evidence_id"]
            ),
            "",
        )
        command = (
            f"pcl evidence show {blocker_evidence_id} --json"
            if blocker_evidence_id
            else f"pcl feature read {feature['id']} --json"
        )
        reason = (
            "The Feature is passing but not done, and one or more Tests lack a passing "
            "hash-bound Evidence Set completion-policy receipt."
            if blockers
            else "The Feature is passing but not done; explicit completion Evidence and a terminal decision remain."
        )
        return build_next_action(
            action_type="review_passing_feature_completion",
            command=command,
            reason=reason,
            target=feature,
            priority=60,
            blocking=False,
            requires_human=False,
            safe_to_run=True,
            expected_after=(
                "The Feature completion blockers and bound Evidence are reviewed before an explicit done transition."
            ),
        )
    finally:
        conn.close()


def _uncovered_feature_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, name, surface, description, status, confidence, created_at, updated_at
            FROM features
            WHERE status IN ('discovered', 'specified', 'needs_test', 'needs_fix')
            ORDER BY created_at, id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        feature = dict(row)
        feature_id = str(feature["id"])
        return build_next_action(
            action_type="cover_feature",
            command=f"pcl goal create --title 'Cover feature {feature_id}'",
            reason="No open goal exists, and a tracked feature still needs coverage work.",
            target=feature,
            priority=65,
            blocking=False,
            requires_human=True,
            safe_to_run=False,
            expected_after="An open goal exists for the uncovered feature and can run feature coverage.",
        )
    finally:
        conn.close()


def _open_escalation_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, workflow_run_id, severity, question, recommendation, status, created_at
            FROM escalations
            WHERE status = 'open'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        escalation = dict(row)
        decisions = [
            dict(decision)
            for decision in conn.execute(
                """
                SELECT id, status, blocks_json, created_at
                FROM decisions
                ORDER BY id
                """
            ).fetchall()
        ]
        linked_decisions = linked_decisions_for_escalation(decisions, str(escalation["id"]))
        linked_decision_ids = [str(decision["id"]) for decision in linked_decisions]
        escalation["linked_decision_ids"] = linked_decision_ids
        if linked_decision_ids:
            decision_id = linked_decision_ids[0]
            command = (
                f"pcl escalation resolve {escalation['id']} --decision {decision_id} "
                "--summary 'Record the outcome'"
            )
            reason = "A human escalation is open and has a linked decision to record in the resolution."
        else:
            command = (
                f"pcl decision open --escalation {escalation['id']} "
                f"--question 'Record the human decision for {escalation['id']}' "
                "--recommendation 'Choose the safe next step'"
            )
            reason = "A human escalation is open and needs a linked durable decision before resolution."
        return build_next_action(
            action_type="resolve_escalation",
            command=command,
            reason=reason,
            target=escalation,
            priority=10,
            blocking=True,
            requires_human=True,
            safe_to_run=False,
            expected_after=(
                "The escalation is resolved with the linked decision."
                if linked_decision_ids
                else "A linked decision exists for the escalation."
            ),
        )
    finally:
        conn.close()


def _open_decision_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT decisions.id, decisions.status, decisions.question,
                   decisions.recommendation, decisions.blocks_json,
                   decisions.created_at,
                   EXISTS(
                     SELECT 1 FROM events
                     WHERE events.event_type = 'profile_decision_proposed'
                       AND events.entity_type = 'decision'
                       AND events.entity_id = decisions.id
                   ) AS profile_proposal
            FROM decisions
            WHERE status = 'open'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        decision = dict(row)
        profile_proposal = bool(decision.pop("profile_proposal"))
        return build_next_action(
            action_type="resolve_decision",
            command=(
                f"pcl decision proposal show {decision['id']} --json"
                if profile_proposal
                else (
                    f"pcl decision resolve {decision['id']} "
                    "--selected-option 'Record the selected option' "
                    "--reason 'Explain the human decision'"
                )
            ),
            reason="A human decision is open and blocks safe continuation.",
            target=decision,
            priority=20,
            blocking=True,
            requires_human=True,
            safe_to_run=False,
            expected_after=(
                "The immutable proposal is shown before a human selects or declines it."
                if profile_proposal
                else "The decision is resolved or waived."
            ),
        )
    finally:
        conn.close()


def _needs_human_escalation_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
        runs = conn.execute(
            f"""
            SELECT id, workflow_id, goal_id, status
            FROM workflow_runs
            WHERE status IN ({placeholders})
            ORDER BY started_at DESC, id DESC
            """,
            tuple(sorted(ACTIVE_RUN_STATUSES)),
        ).fetchall()
        for run in runs:
            verification = conn.execute(
                """
                SELECT
                  verifications.id,
                  verifications.result,
                  verifications.reasons_json,
                  verifications.created_at,
                  events.rowid AS event_rowid
                FROM verifications
                LEFT JOIN events
                  ON events.entity_type = 'verification'
                 AND events.entity_id = verifications.id
                 AND events.event_type = 'verification_recorded'
                WHERE workflow_run_id = ?
                ORDER BY verifications.created_at DESC, verifications.id DESC
                LIMIT 1
                """,
                (run["id"],),
            ).fetchone()
            if verification is None or verification["result"] != "needs_human":
                continue
            escalations = conn.execute(
                """
                SELECT
                  escalations.id,
                  escalations.status,
                  escalations.created_at,
                  events.rowid AS event_rowid
                FROM escalations
                LEFT JOIN events
                  ON events.entity_type = 'escalation'
                 AND events.entity_id = escalations.id
                 AND events.event_type = 'escalation_opened'
                WHERE escalations.workflow_run_id = ?
                ORDER BY escalations.created_at DESC, escalations.id DESC
                """,
                (run["id"],),
            ).fetchall()
            if any(_escalation_opened_at_or_after(escalation, verification) for escalation in escalations):
                continue
            target = dict(run)
            target["verification_id"] = verification["id"]
            target["verification_result"] = verification["result"]
            target["reasons_json"] = verification["reasons_json"]
            target["verification_created_at"] = verification["created_at"]
            return build_next_action(
                action_type="open_escalation",
                command=(
                    f"pcl escalation open --run {run['id']} --severity high "
                    "--question 'What human decision is needed?' "
                    "--recommendation 'Review the needs_human verification and choose the next step'"
                ),
                reason="The latest verification needs human input and no open escalation exists for this run.",
                target=target,
                priority=30,
                blocking=True,
                requires_human=True,
                safe_to_run=False,
                expected_after="An open escalation records the human-required ambiguity for this run.",
            )
        return None
    finally:
        conn.close()


def _escalation_opened_at_or_after(escalation, verification) -> bool:
    escalation_event_rowid = escalation["event_rowid"]
    verification_event_rowid = verification["event_rowid"]
    if escalation_event_rowid is not None and verification_event_rowid is not None:
        return int(escalation_event_rowid) >= int(verification_event_rowid)
    return str(escalation["created_at"]) >= str(verification["created_at"])


def _defect_next_action(defect: dict) -> dict:
    defect_id = defect["id"]
    defect_status = defect.get("status")
    commands = {
        "open": (
            "triage_defect",
            f"pcl defect triage {defect_id} --summary 'Summarize impact and priority'",
            "A defect is open and needs triage before repair starts.",
        ),
        "triaged": (
            "start_defect",
            f"pcl defect start {defect_id} --summary 'Begin repair work'",
            "A triaged defect is ready to start repair.",
        ),
        "in_progress": (
            "fix_defect",
            f"pcl defect fix {defect_id} --summary 'Summarize the fix' --evidence 'Test or commit evidence'",
            "A defect is in progress and needs fix evidence.",
        ),
        "fixed": (
            "verify_defect",
            f"pcl defect verify {defect_id} --summary 'Summarize verification' --verification V-0001",
            "A fixed defect needs an approved verification linked to its repair workflow.",
        ),
        "verified": (
            "close_defect",
            f"pcl defect close {defect_id} --summary 'Close verified defect' --evidence 'Verification evidence'",
            "A verified defect can be closed with evidence.",
        ),
    }
    action_type, command, reason = commands.get(
        str(defect_status),
        (
            "repair_defect",
            f"pcl loop run defect_repair --defect {defect_id}",
            "There is at least one active defect.",
        ),
    )
    return build_next_action(
        action_type=action_type,
        command=command,
        reason=reason,
        target=defect,
        priority=50,
        blocking=False,
        requires_human=False,
        safe_to_run=False,
        expected_after=f"Defect {defect_id} advances beyond {defect_status}.",
    )


def _expired_lease_next_action(paths: ProjectPaths) -> dict | None:
    job_ids = expired_lease_job_ids(paths)
    if not job_ids:
        return None
    return build_next_action(
        action_type="reap_expired_leases",
        command="pcl jobs reap",
        reason=f"Running agent job leases have expired: {', '.join(job_ids)}.",
        target={"expired_job_ids": job_ids},
        priority=44,
        blocking=False,
        requires_human=False,
        safe_to_run=True,
        expected_after="Expired leases are requeued or blocked with an escalation when attempts are exhausted.",
    )


def _workflow_proposal_review_next_action(paths: ProjectPaths) -> dict | None:
    proposal = next_reviewable_workflow_proposal(paths)
    if proposal is None:
        return None
    proposal_id = str(proposal["id"])
    return build_next_action(
        action_type="review_workflow_proposal",
        command=f"pcl workflow proposals approve {proposal_id} --summary 'Approve this workflow template'",
        reason="A workflow proposal is waiting for human review before it can become executable.",
        target=proposal,
        priority=55,
        blocking=False,
        requires_human=True,
        safe_to_run=False,
        expected_after="The proposal is approved into `.project-loop/workflows/` or cancelled.",
    )


def _checkpoint_review_next_action(paths: ProjectPaths) -> dict | None:
    status = checkpoint_status(paths)
    if not status["checkpoint_requires_human"]:
        return None
    completed = status["completed_features_since_checkpoint"]
    threshold = status["threshold"]
    return build_next_action(
        action_type="checkpoint_review",
        command=(
            "pcl checkpoint record --review-type integration "
            "--summary 'Review commit/package checkpoint, UX checklist, and next big-goal priority' "
            "--evidence 'Reviewed code state, validation results, UX checklist, and next feature priority'"
        ),
        reason=(
            f"{completed} features were marked done since the last checkpoint; "
            f"the checkpoint threshold is {threshold}. Pause before another feature coverage run "
            "and review the larger product goal."
        ),
        target=status,
        priority=58,
        blocking=False,
        requires_human=True,
        safe_to_run=False,
        expected_after=(
            "A checkpoint_review evidence record exists, and `pcl next` can resume normal goal routing."
        ),
    )


def _task_next_action(paths: ProjectPaths, *, goal_id: str | None = None) -> dict | None:
    conn = connect(paths.db_path)
    try:
        in_progress = _next_considered_task(
            conn,
            statuses=("in_progress",),
            goal_id=goal_id,
        )
        if in_progress is not None:
            task = _task_next_action_target(conn, dict(in_progress))
            task_id = str(task["id"])
            return build_next_action(
                action_type="work_on_task",
                command=f"pcl context pack --task {task_id} --json",
                reason=(
                    "A task under an open goal is already in progress; finish that task before "
                    "starting another backlog item."
                ),
                target=task,
                priority=59,
                blocking=False,
                requires_human=False,
                safe_to_run=True,
                expected_after=f"The task context pack is reviewed and task {task_id} advances toward done.",
            )

        actionable = _next_actionable_task(conn, goal_id=goal_id)
        if actionable is None:
            return None
        task = _task_next_action_target(conn, dict(actionable))
        task_id = str(task["id"])
        return build_next_action(
            action_type="work_on_task",
            command=f"pcl context pack --task {task_id} --json",
            reason=(
                "This is the highest-priority ready task under an open goal with all "
                "dependencies satisfied."
            ),
            target=task,
            priority=59,
            blocking=False,
            requires_human=False,
            safe_to_run=True,
            expected_after=f"The task context pack is reviewed and task {task_id} advances toward done.",
        )
    finally:
        conn.close()


def _next_considered_task(
    conn,
    *,
    statuses: tuple[str, ...],
    goal_id: str | None = None,
):
    rows = _next_task_candidates(conn, statuses=statuses, goal_id=goal_id, limit=1)
    return rows[0] if rows else None


def _next_task_candidates(
    conn,
    *,
    statuses: tuple[str, ...],
    goal_id: str | None = None,
    limit: int | None = None,
):
    placeholders = ", ".join("?" for _ in statuses)
    goal_filter = "AND tasks.related_goal_id = ?" if goal_id else ""
    limit_clause = "LIMIT 1" if limit == 1 else ""
    params = list(statuses)
    if goal_id:
        params.append(goal_id)
    return conn.execute(
        f"""
        SELECT
          tasks.id,
          tasks.title,
          tasks.description,
          tasks.status,
          tasks.priority,
          tasks.owner,
          tasks.risk,
          tasks.effort,
          tasks.related_goal_id,
          tasks.related_feature_id,
          tasks.related_defect_id,
          tasks.created_at,
          tasks.updated_at,
          goals.status AS related_goal_status
        FROM tasks
        JOIN goals ON goals.id = tasks.related_goal_id
        WHERE goals.status IN ('open', 'active')
          AND tasks.status IN ({placeholders})
          {goal_filter}
        ORDER BY tasks.priority, tasks.id
        {limit_clause}
        """,
        tuple(params),
    ).fetchall()


def _next_actionable_task(conn, *, goal_id: str | None = None):
    rows = _next_actionable_task_candidates(conn, goal_id=goal_id, limit=1)
    return rows[0] if rows else None


def _next_actionable_task_candidates(
    conn,
    *,
    goal_id: str | None = None,
    limit: int | None = None,
):
    status_placeholders = ", ".join("?" for _ in TASK_ACTIONABLE_STATUSES)
    completed_placeholders = ", ".join("?" for _ in TASK_COMPLETED_DEPENDENCY_STATUSES)
    goal_filter = "AND tasks.related_goal_id = ?" if goal_id else ""
    limit_clause = "LIMIT 1" if limit == 1 else ""
    params = list(sorted(TASK_ACTIONABLE_STATUSES))
    params.extend(sorted(TASK_COMPLETED_DEPENDENCY_STATUSES))
    if goal_id:
        params.append(goal_id)
    return conn.execute(
        f"""
        SELECT
          tasks.id,
          tasks.title,
          tasks.description,
          tasks.status,
          tasks.priority,
          tasks.owner,
          tasks.risk,
          tasks.effort,
          tasks.related_goal_id,
          tasks.related_feature_id,
          tasks.related_defect_id,
          tasks.created_at,
          tasks.updated_at,
          goals.status AS related_goal_status
        FROM tasks
        JOIN goals ON goals.id = tasks.related_goal_id
        WHERE goals.status IN ('open', 'active')
          AND tasks.status IN ({status_placeholders})
          AND NOT EXISTS (
            SELECT 1
            FROM task_dependencies
            JOIN tasks AS dependency
              ON dependency.id = task_dependencies.depends_on_task_id
            WHERE task_dependencies.task_id = tasks.id
              AND dependency.status NOT IN ({completed_placeholders})
          )
          {goal_filter}
        ORDER BY tasks.priority, tasks.id
        {limit_clause}
        """,
        tuple(params),
    ).fetchall()


def _task_next_action_target(conn, task: dict) -> dict:
    dependency_rows = conn.execute(
        """
        SELECT depends_on_task_id
        FROM task_dependencies
        WHERE task_id = ?
        ORDER BY depends_on_task_id
        """,
        (task["id"],),
    ).fetchall()
    dependent_rows = conn.execute(
        """
        SELECT task_id
        FROM task_dependencies
        WHERE depends_on_task_id = ?
        ORDER BY task_id
        """,
        (task["id"],),
    ).fetchall()
    task["dependency_ids"] = [str(row["depends_on_task_id"]) for row in dependency_rows]
    task["dependent_ids"] = [str(row["task_id"]) for row in dependent_rows]
    return task


def _unfinished_executor_next_action(
    paths: ProjectPaths,
    *,
    goal_id: str | None = None,
) -> dict | None:
    conn = connect(paths.db_path)
    try:
        placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
        goal_filter = "AND goal_id = ?" if goal_id else ""
        params = list(sorted(ACTIVE_RUN_STATUSES))
        if goal_id:
            params.append(goal_id)
        runs = conn.execute(
            f"""
            SELECT id, workflow_id, goal_id, status, iteration, started_at
            FROM workflow_runs
            WHERE status IN ({placeholders})
              {goal_filter}
            ORDER BY started_at DESC, id DESC
            """,
            tuple(params),
        ).fetchall()
        for run in runs:
            latest_event = conn.execute(
                """
                SELECT event_type, rowid
                FROM events
                WHERE entity_type = 'workflow_run'
                  AND entity_id = ?
                  AND event_type IN (
                    'workflow_execution_started',
                    'workflow_execution_resumed',
                    'workflow_execution_finished'
                  )
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (run["id"],),
            ).fetchone()
            if latest_event is None or latest_event["event_type"] == "workflow_execution_finished":
                continue
            target = dict(run)
            target["latest_executor_event"] = latest_event["event_type"]
            target["latest_executor_event_rowid"] = latest_event["rowid"]
            return build_next_action(
                action_type="resume_workflow_execution",
                command=f"pcl loop execute {run['workflow_id']} --resume {run['id']}",
                reason="An executor-owned workflow run is active without a finished execution event.",
                target=target,
                priority=35,
                blocking=True,
                requires_human=False,
                safe_to_run=False,
                expected_after="The existing workflow run has workflow execution evidence and a terminal status or next verification step.",
            )
        return None
    finally:
        conn.close()


def _failed_executor_retry_next_action(
    paths: ProjectPaths,
    *,
    goal_id: str | None = None,
) -> dict | None:
    conn = connect(paths.db_path)
    try:
        retried_run_ids = _retried_workflow_run_ids(conn)
        goal_filter = "AND goal_id = ?" if goal_id else ""
        rows = conn.execute(
            f"""
            SELECT id, workflow_id, goal_id, status, iteration, started_at, ended_at, summary
            FROM workflow_runs
            WHERE status = 'failed'
              {goal_filter}
            ORDER BY ended_at DESC, started_at DESC, id DESC
            """,
            (goal_id,) if goal_id else (),
        ).fetchall()
        for row in rows:
            run_id = str(row["id"])
            if run_id in retried_run_ids:
                continue
            finished = conn.execute(
                """
                SELECT payload_json, rowid
                FROM events
                WHERE entity_type = 'workflow_run'
                  AND entity_id = ?
                  AND event_type = 'workflow_execution_finished'
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if finished is None:
                continue
            payload = _parse_event_payload(str(finished["payload_json"] or "{}"))
            if payload.get("status") != "failed":
                continue
            target = dict(row)
            target["executor_event_rowid"] = finished["rowid"]
            target["failure_reason"] = payload.get("failure_reason") or row["summary"]
            target["evidence_id"] = payload.get("evidence_id") or ""
            return build_next_action(
                action_type="retry_workflow_execution",
                command=f"pcl loop execute {row['workflow_id']} --retry {run_id}",
                reason="The latest unretried executor workflow run failed and can be retried explicitly.",
                target=target,
                priority=45,
                blocking=False,
                requires_human=False,
                safe_to_run=False,
                expected_after="A new workflow run is linked to the failed run and records fresh execution evidence.",
            )
        return None
    finally:
        conn.close()


def _retried_workflow_run_ids(conn) -> set[str]:
    rows = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE event_type = 'workflow_execution_retried'
        ORDER BY rowid
        """
    ).fetchall()
    retried: set[str] = set()
    for row in rows:
        payload = _parse_event_payload(str(row["payload_json"] or "{}"))
        retry_of = payload.get("retry_of_workflow_run_id")
        if isinstance(retry_of, str) and retry_of:
            retried.add(retry_of)
    return retried


def _parse_event_payload(payload_json: str) -> dict:
    try:
        payload = json.loads(payload_json)
    except JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _active_workflow_next_action(
    paths: ProjectPaths,
    *,
    goal_id: str | None = None,
) -> dict | None:
    conn = connect(paths.db_path)
    try:
        placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
        goal_filter = "AND goal_id = ?" if goal_id else ""
        params = list(sorted(ACTIVE_RUN_STATUSES))
        if goal_id:
            params.append(goal_id)
        run = conn.execute(
            f"""
            SELECT id, workflow_id, goal_id, status
            FROM workflow_runs
            WHERE status IN ({placeholders})
              {goal_filter}
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if run is None:
            return None

        return _workflow_run_next_action(conn, run)
    finally:
        conn.close()


def active_workflow_next_action(paths: ProjectPaths) -> dict | None:
    """Return the existing router action for a nonterminal workflow run, if any."""

    return _active_workflow_next_action(paths)


def _workflow_run_next_action(conn, run) -> dict:
    job_placeholders = ", ".join("?" for _ in ACTIVE_JOB_STATUSES)
    active_job = conn.execute(
        f"""
        SELECT id, role, status
        FROM agent_jobs
        WHERE workflow_run_id = ? AND status IN ({job_placeholders})
        ORDER BY id
        LIMIT 1
        """,
        (run["id"], *tuple(sorted(ACTIVE_JOB_STATUSES))),
    ).fetchone()
    target = dict(run)
    if active_job is not None:
        target["job"] = dict(active_job)
        return build_next_action(
            action_type="continue_workflow",
            command=f"pcl jobs read {active_job['id']}",
            reason="A workflow run is already active and has queued or running jobs.",
            target=target,
            priority=40,
            blocking=False,
            requires_human=False,
            safe_to_run=True,
            expected_after="The agent job prompt is reviewed and the job can be executed or completed.",
        )

    job_statuses = _job_status_counts(conn, str(run["id"]))
    failed_or_cancelled = {
        status: count
        for status, count in job_statuses.items()
        if status in TERMINAL_JOB_STATUSES and status != "passed" and count
    }
    target["job_statuses"] = job_statuses
    if failed_or_cancelled:
        return build_next_action(
            action_type="resolve_workflow_failure",
            command=f"pcl loop fail {run['id']} --summary 'Explain why this run failed'",
            reason="The active workflow has failed or cancelled jobs.",
            target=target,
            priority=40,
            blocking=True,
            requires_human=False,
            safe_to_run=False,
            expected_after="The active workflow is marked failed or otherwise resolved.",
        )

    approved = conn.execute(
        "SELECT id FROM verifications WHERE workflow_run_id = ? AND result = 'approved' ORDER BY created_at DESC LIMIT 1",
        (run["id"],),
    ).fetchone()
    if approved is None:
        return build_next_action(
            action_type="record_verification",
            command=f"pcl verification record --run {run['id']} --result approved --reason 'Summarize verification evidence'",
            reason="All active workflow jobs are terminal, but no approved verification exists.",
            target=target,
            priority=40,
            blocking=True,
            requires_human=True,
            safe_to_run=False,
            expected_after="An approved, rejected, inconclusive, or needs_human verification exists for the run.",
        )
    target["verification_id"] = approved["id"]
    return build_next_action(
        action_type="complete_workflow",
        command=f"pcl loop complete {run['id']} --summary 'Summarize completed workflow'",
        reason="The active workflow has passed jobs and an approved verification.",
        target=target,
        priority=40,
        blocking=False,
        requires_human=False,
        safe_to_run=False,
        expected_after="The workflow run is marked passed.",
    )


def _job_status_counts(conn, workflow_run_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM agent_jobs WHERE workflow_run_id = ? GROUP BY status",
        (workflow_run_id,),
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}
