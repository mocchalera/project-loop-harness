from __future__ import annotations


from .db import connect
from .errors import InvalidInputError
from .guards import require_initialized
from .lifecycle import ACTIVE_RUN_STATUSES
from .paths import ProjectPaths

from .action_routing import (
    _active_workflow_next_action,
    _continue_goal_next_action,
    _workflow_run_next_action,
    build_next_action,
)
from .command_domain import loop_status


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
