from __future__ import annotations

import json
from json import JSONDecodeError

from .checkpoints import checkpoint_status
from .db import connect, connect_mutation
from .dispatch import expired_lease_job_ids
from .evidence import record_inline_evidence
from .events import append_event
from .errors import InvalidInputError
from .guards import require_initialized
from .ids import next_prefixed_id
from .lifecycle import ACTIVE_JOB_STATUSES, ACTIVE_RUN_STATUSES, TERMINAL_JOB_STATUSES
from .links import linked_decisions_for_escalation
from .locales import HUMAN_GATE_JA
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .workflow_proposals import next_reviewable_workflow_proposal


FEATURE_STATUSES = {"discovered", "specified", "needs_test", "needs_fix", "passing", "done", "waived"}
TASK_ACTIONABLE_STATUSES = {"todo", "ready"}
TASK_COMPLETED_DEPENDENCY_STATUSES = {"done", "cancelled", "waived"}


def _normalized_json_object(raw: str, field_name: str) -> str:
    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise InvalidInputError(
            f"{field_name} must be valid JSON: {exc.msg}.",
            details={"field": field_name, "position": exc.pos},
        ) from exc
    if not isinstance(value, dict):
        raise InvalidInputError(
            f"{field_name} must be a JSON object.",
            details={"field": field_name, "type": type(value).__name__},
        )
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def create_goal(paths: ProjectPaths, *, title: str, completion_json: str = "{}", budget_json: str = "{}") -> str:
    require_initialized(paths)
    completion_json = _normalized_json_object(completion_json, "completion-json")
    budget_json = _normalized_json_object(budget_json, "budget-json")

    conn = connect_mutation(paths)
    try:
        goal_id = next_prefixed_id(conn, "goals", "G")
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO goals(id, title, status, completion_json, stop_conditions_json, budget_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (goal_id, title, "open", completion_json, "{}", budget_json, now, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="goal_created",
            entity_type="goal",
            entity_id=goal_id,
            payload={"title": title},
        )
        conn.commit()
        return goal_id
    finally:
        conn.close()


def add_feature(paths: ProjectPaths, *, name: str, surface: str, description: str = "", evidence: str = "") -> str:
    require_initialized(paths)

    conn = connect_mutation(paths)
    try:
        feature_id = next_prefixed_id(conn, "features", "F")
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO features(id, name, surface, description, status, confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (feature_id, name, surface, description, "discovered", "medium", now, now),
        )
        payload = {"name": name, "surface": surface, "description": description, "evidence": evidence}
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="feature_added",
            entity_type="feature",
            entity_id=feature_id,
            payload=payload,
        )
        conn.commit()
        return feature_id
    finally:
        conn.close()


def list_features(paths: ProjectPaths, *, status: str | None = None) -> list[dict]:
    require_initialized(paths)
    if status:
        _require_feature_status(status)

    clauses: list[str] = []
    params: list[str] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT id, name, surface, description, status, confidence, created_at, updated_at
            FROM features
            {where_sql}
            ORDER BY id
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def read_feature(paths: ProjectPaths, feature_id: str) -> dict:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")

    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, name, surface, description, status, confidence, created_at, updated_at
            FROM features
            WHERE id = ?
            """,
            (feature_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Feature does not exist: {feature_id}",
                details={"feature_id": feature_id},
            )
        return dict(row)
    finally:
        conn.close()


def set_feature_status(
    paths: ProjectPaths,
    feature_id: str,
    *,
    status: str,
    summary: str,
    evidence: str,
) -> dict:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")
    _require_feature_status(status)

    conn = connect_mutation(paths)
    try:
        feature = conn.execute(
            "SELECT id, status FROM features WHERE id = ?",
            (feature_id,),
        ).fetchone()
        if feature is None:
            raise InvalidInputError(
                f"Feature does not exist: {feature_id}",
                details={"feature_id": feature_id},
            )
        previous_status = str(feature["status"])
        if previous_status == status:
            return {
                "ok": True,
                "feature_id": feature_id,
                "previous_status": previous_status,
                "status": status,
                "changed": False,
                "evidence_recorded": False,
            }

        _require_text(summary, "--summary is required to update feature status.")
        _require_text(
            evidence,
            "--evidence is required to update feature status. Use command output, artifact path, "
            "screenshot path, commit, or report path.",
        )

        now = utc_now_iso()
        evidence_id = record_inline_evidence(
            conn,
            evidence_type="feature_status",
            summary=evidence.strip(),
            context=f"feature/{feature_id}/status",
            command="pcl feature status",
        )
        conn.execute(
            "UPDATE features SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, feature_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="feature_status_updated",
            entity_type="feature",
            entity_id=feature_id,
            payload={
                "previous_status": previous_status,
                "status": status,
                "summary": summary.strip(),
                "evidence": evidence.strip(),
                "evidence_id": evidence_id,
                "source": "manual",
            },
        )
        conn.commit()
        return {
            "ok": True,
            "feature_id": feature_id,
            "previous_status": previous_status,
            "status": status,
            "summary": summary.strip(),
            "evidence_id": evidence_id,
            "changed": True,
        }
    finally:
        conn.close()


def open_defect(
    paths: ProjectPaths,
    *,
    feature_id: str,
    severity: str,
    expected: str,
    actual: str,
    test_case_id: str | None = None,
    reproduction: str = "",
    evidence: str = "",
) -> str:
    require_initialized(paths)

    conn = connect_mutation(paths)
    try:
        row = conn.execute("SELECT id FROM features WHERE id = ?", (feature_id,)).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Feature does not exist: {feature_id}",
                details={"feature_id": feature_id},
            )
        defect_id = next_prefixed_id(conn, "defects", "D")
        now = utc_now_iso()
        evidence_id = None
        if evidence.strip():
            evidence_id = record_inline_evidence(
                conn,
                evidence_type="defect_open",
                summary=evidence.strip(),
                context=f"defect/{defect_id}/open",
                command="pcl defect open",
            )
        conn.execute(
            """
            INSERT INTO defects(id, feature_id, test_case_id, severity, expected, actual, reproduction, status, evidence_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                defect_id,
                feature_id,
                test_case_id or None,
                severity,
                expected,
                actual,
                reproduction,
                "open",
                evidence_id,
                now,
                now,
            ),
        )
        conn.execute("UPDATE features SET status = ?, updated_at = ? WHERE id = ?", ("needs_fix", now, feature_id))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="defect_opened",
            entity_type="defect",
            entity_id=defect_id,
            payload={
                "feature_id": feature_id,
                "severity": severity,
                "expected": expected,
                "actual": actual,
                "test_case_id": test_case_id,
                "evidence": evidence,
                "evidence_id": evidence_id,
            },
        )
        conn.commit()
        return defect_id
    finally:
        conn.close()


def loop_status(paths: ProjectPaths) -> dict:
    require_initialized(paths)

    conn = connect(paths.db_path)
    try:
        open_goals = conn.execute(
            """
            SELECT id, title, status
            FROM goals
            WHERE status NOT IN ('closed', 'cancelled')
            ORDER BY created_at DESC
            """
        ).fetchall()
        open_defects = conn.execute(
            """
            SELECT id, feature_id, severity, status
            FROM defects
            WHERE status NOT IN ('closed', 'waived')
            ORDER BY created_at DESC
            """
        ).fetchall()
        runs = conn.execute("SELECT id, workflow_id, status, iteration FROM workflow_runs ORDER BY started_at DESC LIMIT 10").fetchall()
        return {
            "open_goals": [dict(r) for r in open_goals],
            "open_defects": [dict(r) for r in open_defects],
            "recent_workflow_runs": [dict(r) for r in runs],
        }
    finally:
        conn.close()


def build_next_action(
    *,
    action_type: str,
    command: str,
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


def next_action(paths: ProjectPaths) -> dict:
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
    task = _task_next_action(paths)
    if task is not None:
        return task
    if status["open_goals"]:
        goal = status["open_goals"][0]
        return _continue_goal_next_action(goal)
    uncovered_feature = _uncovered_feature_next_action(paths)
    if uncovered_feature is not None:
        return uncovered_feature
    return build_next_action(
        action_type="create_goal",
        command="pcl goal create --title 'Reach feature coverage'",
        reason="No open goal exists.",
        target=None,
        priority=70,
        blocking=False,
        requires_human=True,
        safe_to_run=False,
        expected_after="An open goal exists and `pcl next` can route work from it.",
    )


def finish_plan(paths: ProjectPaths, *, run_id: str | None = None, goal_id: str | None = None) -> dict:
    require_initialized(paths)

    if run_id:
        return _finish_plan_for_run(paths, run_id=run_id, goal_id=goal_id)

    if goal_id:
        conn = connect(paths.db_path)
        try:
            selected_goal = _finish_goal_row(conn, goal_id)
        finally:
            conn.close()
        return _finish_plan_for_goal(paths, goal=selected_goal)

    active = _active_workflow_next_action(paths)
    if active is not None:
        target = active.get("target") or {}
        return _finish_payload(
            run_id=target.get("id"),
            goal_id=target.get("goal_id"),
            remaining_steps=[_finish_step(active)],
        )

    status = loop_status(paths)
    selected_goal = None
    if status["open_goals"]:
        selected_goal = status["open_goals"][0]

    if selected_goal is None:
        return _finish_payload(run_id=None, goal_id=None, remaining_steps=[])

    return _finish_plan_for_goal(paths, goal=dict(selected_goal))


def _finish_plan_for_run(paths: ProjectPaths, *, run_id: str, goal_id: str | None = None) -> dict:
    conn = connect(paths.db_path)
    try:
        run = _finish_workflow_run(conn, run_id)
        run_goal_id = run["goal_id"]
        if goal_id and run_goal_id and goal_id != run_goal_id:
            raise InvalidInputError(
                f"Workflow run {run_id} belongs to goal {run_goal_id}, not {goal_id}.",
                details={"workflow_run_id": run_id, "goal_id": goal_id, "run_goal_id": run_goal_id},
            )
        target_goal_id = run_goal_id or goal_id
        if str(run["status"]) in ACTIVE_RUN_STATUSES:
            action = _workflow_run_next_action(conn, run)
            return _finish_payload(
                run_id=run["id"],
                goal_id=target_goal_id,
                remaining_steps=[_finish_step(action)],
            )
        if target_goal_id:
            goal = _finish_goal_row(conn, str(target_goal_id))
            action = _goal_close_next_action(conn, run=run, goal=goal)
            if action is not None:
                return _finish_payload(
                    run_id=run["id"],
                    goal_id=target_goal_id,
                    remaining_steps=[_finish_step(action)],
                )
        return _finish_payload(run_id=run["id"], goal_id=target_goal_id, remaining_steps=[])
    finally:
        conn.close()


def _finish_plan_for_goal(paths: ProjectPaths, *, goal: dict) -> dict:
    conn = connect(paths.db_path)
    try:
        fresh_goal = _finish_goal_row(conn, str(goal["id"]))
        run = _latest_workflow_run_for_goal(conn, str(fresh_goal["id"]))
        if run is None:
            if fresh_goal["status"] in {"closed", "cancelled"}:
                return _finish_payload(run_id=None, goal_id=fresh_goal["id"], remaining_steps=[])
            return _finish_payload(
                run_id=None,
                goal_id=fresh_goal["id"],
                remaining_steps=[_finish_step(_continue_goal_next_action(fresh_goal))],
            )
        if str(run["status"]) in ACTIVE_RUN_STATUSES:
            action = _workflow_run_next_action(conn, run)
            return _finish_payload(
                run_id=run["id"],
                goal_id=fresh_goal["id"],
                remaining_steps=[_finish_step(action)],
            )
        action = _goal_close_next_action(conn, run=run, goal=fresh_goal)
        if action is not None:
            return _finish_payload(
                run_id=run["id"],
                goal_id=fresh_goal["id"],
                remaining_steps=[_finish_step(action)],
            )
        if fresh_goal["status"] not in {"closed", "cancelled"} and str(run["status"]) != "passed":
            return _finish_payload(
                run_id=run["id"],
                goal_id=fresh_goal["id"],
                remaining_steps=[_finish_step(_continue_goal_next_action(fresh_goal))],
            )
        return _finish_payload(run_id=run["id"], goal_id=fresh_goal["id"], remaining_steps=[])
    finally:
        conn.close()


def _finish_payload(*, run_id: str | None, goal_id: str | None, remaining_steps: list[dict]) -> dict:
    return {
        "target": {"run": run_id, "goal": goal_id},
        "finished": not remaining_steps,
        "remaining_steps": remaining_steps,
        "next_command": remaining_steps[0]["command"] if remaining_steps else None,
    }


def _finish_step(action: dict) -> dict:
    return {
        "type": action["type"],
        "command": action["command"],
        "reason": action["reason"],
        "requires_human": action["requires_human"],
        "safe_to_run": action["safe_to_run"],
    }


def _finish_workflow_run(conn, run_id: str):
    row = conn.execute(
        """
        SELECT id, workflow_id, goal_id, status
        FROM workflow_runs
        WHERE id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Workflow run does not exist: {run_id}",
            details={"workflow_run_id": run_id},
        )
    return row


def _finish_goal_row(conn, goal_id: str):
    row = conn.execute(
        """
        SELECT id, title, status
        FROM goals
        WHERE id = ?
        """,
        (goal_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Goal does not exist: {goal_id}", details={"goal_id": goal_id})
    return dict(row)


def _latest_workflow_run_for_goal(conn, goal_id: str):
    return conn.execute(
        """
        SELECT id, workflow_id, goal_id, status
        FROM workflow_runs
        WHERE goal_id = ?
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (goal_id,),
    ).fetchone()


def _goal_close_next_action(conn, *, run, goal: dict) -> dict | None:
    if str(run["status"]) != "passed" or goal["status"] in {"closed", "cancelled"}:
        return None
    verification = conn.execute(
        "SELECT id FROM verifications WHERE workflow_run_id = ? AND result = 'approved' ORDER BY created_at DESC LIMIT 1",
        (run["id"],),
    ).fetchone()
    verification_id = verification["id"] if verification is not None else None
    command = f"pcl goal close {goal['id']} --summary 'Summarize completed goal'"
    if verification_id:
        command += f" --verification {verification_id}"
    target = {
        "id": goal["id"],
        "status": goal["status"],
        "run": {"id": run["id"], "status": run["status"]},
    }
    if verification_id:
        target["verification_id"] = verification_id
    return build_next_action(
        action_type="close_goal",
        command=command,
        reason="The workflow run has passed and its goal is still open.",
        target=target,
        priority=45,
        blocking=True,
        requires_human=True,
        safe_to_run=False,
        expected_after="The goal is closed with reviewed completion evidence.",
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
            SELECT id, status, question, recommendation, blocks_json, created_at
            FROM decisions
            WHERE status = 'open'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        decision = dict(row)
        return build_next_action(
            action_type="resolve_decision",
            command=(
                f"pcl decision resolve {decision['id']} "
                "--selected-option 'Record the selected option' --reason 'Explain the human decision'"
            ),
            reason="A human decision is open and blocks safe continuation.",
            target=decision,
            priority=20,
            blocking=True,
            requires_human=True,
            safe_to_run=False,
            expected_after="The decision is resolved or waived.",
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
    if not status["checkpoint_recommended"]:
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


def _task_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        in_progress = _next_considered_task(conn, statuses=("in_progress",))
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

        actionable = _next_actionable_task(conn)
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


def _next_considered_task(conn, *, statuses: tuple[str, ...]):
    placeholders = ", ".join("?" for _ in statuses)
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
        ORDER BY tasks.priority, tasks.id
        LIMIT 1
        """,
        tuple(statuses),
    ).fetchone()


def _next_actionable_task(conn):
    status_placeholders = ", ".join("?" for _ in TASK_ACTIONABLE_STATUSES)
    completed_placeholders = ", ".join("?" for _ in TASK_COMPLETED_DEPENDENCY_STATUSES)
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
        ORDER BY tasks.priority, tasks.id
        LIMIT 1
        """,
        tuple(sorted(TASK_ACTIONABLE_STATUSES)) + tuple(sorted(TASK_COMPLETED_DEPENDENCY_STATUSES)),
    ).fetchone()


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


def _unfinished_executor_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
        runs = conn.execute(
            f"""
            SELECT id, workflow_id, goal_id, status, iteration, started_at
            FROM workflow_runs
            WHERE status IN ({placeholders})
            ORDER BY started_at DESC, id DESC
            """,
            tuple(sorted(ACTIVE_RUN_STATUSES)),
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


def _failed_executor_retry_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        retried_run_ids = _retried_workflow_run_ids(conn)
        rows = conn.execute(
            """
            SELECT id, workflow_id, goal_id, status, iteration, started_at, ended_at, summary
            FROM workflow_runs
            WHERE status = 'failed'
            ORDER BY ended_at DESC, started_at DESC, id DESC
            """
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


def _active_workflow_next_action(paths: ProjectPaths) -> dict | None:
    conn = connect(paths.db_path)
    try:
        placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
        run = conn.execute(
            f"""
            SELECT id, workflow_id, goal_id, status
            FROM workflow_runs
            WHERE status IN ({placeholders})
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            tuple(sorted(ACTIVE_RUN_STATUSES)),
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


def to_pretty_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _require_feature_status(status: str) -> None:
    if status not in FEATURE_STATUSES:
        raise InvalidInputError(
            f"Invalid feature status: {status}",
            details={"status": status, "allowed": sorted(FEATURE_STATUSES)},
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
