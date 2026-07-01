from __future__ import annotations

import json
from json import JSONDecodeError

from .checkpoints import checkpoint_status
from .db import connect
from .evidence import record_inline_evidence
from .events import append_event
from .errors import InvalidInputError
from .guards import require_initialized
from .ids import next_prefixed_id
from .lifecycle import ACTIVE_JOB_STATUSES, ACTIVE_RUN_STATUSES, TERMINAL_JOB_STATUSES
from .links import linked_decisions_for_escalation
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .workflow_proposals import next_reviewable_workflow_proposal


FEATURE_STATUSES = {"discovered", "specified", "needs_test", "needs_fix", "passing", "done", "waived"}


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

    conn = connect(paths.db_path)
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

    conn = connect(paths.db_path)
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
    _require_text(summary, "--summary is required to update feature status.")
    _require_text(
        evidence,
        "--evidence is required to update feature status. Use command output, artifact path, "
        "screenshot path, commit, or report path.",
    )

    conn = connect(paths.db_path)
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
            raise InvalidInputError(
                f"Feature {feature_id} is already {status}.",
                details={"feature_id": feature_id, "status": status},
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

    conn = connect(paths.db_path)
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
    return {
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
    if status["open_goals"]:
        goal = status["open_goals"][0]
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
    finally:
        conn.close()


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
