from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from .commands import active_workflow_next_action, create_goal, loop_status, next_action
from .db import connect_mutation
from .evidence import record_inline_evidence
from .events import append_event
from .errors import InvalidInputError, ProjectNotInitializedError
from .init_project import init_project, plan_init_project
from .paths import ProjectPaths
from .tasks import create_task
from .timeutil import utc_now_iso


START_CONTRACT_VERSION = "pcl-start/v1"
START_RECEIPT_CONTRACT_VERSION = "start-receipt/v1"
START_ACTOR = "pcl:start"


def start_work(
    paths: ProjectPaths,
    *,
    intent: str,
    dry_run: bool = False,
    no_init: bool = False,
    new: bool = False,
) -> dict[str, Any]:
    if not intent.strip():
        raise InvalidInputError("intent must not be empty.", details={"field": "intent"})

    initialized = paths.db_path.is_file()
    if not initialized and no_init:
        raise ProjectNotInitializedError(root=str(paths.root))

    init_plan = None
    if not initialized:
        init_plan = plan_init_project(paths)
        if not init_plan.ok:
            return _payload(
                status="init_blocked",
                mutated=False,
                result={
                    "intent": intent,
                    "project_initialized": False,
                    "initialization": init_plan.to_dict(),
                    "created_ids": {},
                    "target": None,
                    "receipt": None,
                },
                next_actions=[
                    _next_action(
                        text="Resolve the reported initialization conflicts, then run pcl start again.",
                        command=None,
                        target=None,
                    )
                ],
            )

    if initialized and not new:
        active = _active_work(paths)
        if active is not None:
            return _active_payload(intent=intent, active=active)

    if dry_run:
        return _payload(
            status="planned",
            mutated=False,
            result={
                "intent": intent,
                "project_initialized": initialized,
                "initialization": None if init_plan is None else init_plan.to_dict(),
                "planned_entities": [
                    {"type": "goal", "status": "open", "title": intent},
                    {
                        "type": "task",
                        "status": "todo",
                        "title": intent,
                        "related_goal": "created_goal",
                    },
                    {"type": "evidence", "contract_version": START_RECEIPT_CONTRACT_VERSION},
                    {"type": "event", "event_type": "work_started"},
                ],
                "created_ids": {},
                "target": {"type": "task", "id": None},
                "receipt": None,
            },
            next_actions=[
                _next_action(
                    text="Apply this plan by running pcl start without --dry-run.",
                    command=None,
                    target=None,
                )
            ],
        )

    project_initialized = False
    if not initialized:
        result = init_project(paths)
        project_initialized = result.created

    goal_id = create_goal(paths, title=intent)
    task = create_task(paths, title=intent, goal_id=goal_id)
    task_id = str(task["id"])
    action = next_action(paths)
    receipt = {
        "contract_version": START_RECEIPT_CONTRACT_VERSION,
        "generated_at": utc_now_iso(),
        "intent": intent,
        "actor": START_ACTOR,
        "repository_revision": _repository_revision(paths.root),
        "created_ids": {"goal": goal_id, "task": task_id},
        "target": {"type": "task", "id": task_id},
    }
    evidence_id, event_id = _record_start_receipt(paths, receipt=receipt)

    return _payload(
        status="started",
        mutated=True,
        result={
            "intent": intent,
            "project_initialized": project_initialized,
            "initialization": None if init_plan is None else init_plan.to_dict(),
            "created_ids": {"goal": goal_id, "task": task_id, "evidence": evidence_id, "event": event_id},
            "target": {"type": "task", "id": task_id},
            "receipt": {**receipt, "evidence_id": evidence_id, "event_id": event_id},
        },
        next_actions=[
            _next_action(
                text="Review the task context and begin the requested work.",
                command=str(action["command"]),
                target={"type": "task", "id": task_id},
            )
        ],
    )


def _active_work(paths: ProjectPaths) -> dict[str, Any] | None:
    status = loop_status(paths)
    active_workflow = active_workflow_next_action(paths)
    if not status["open_goals"] and not status["open_defects"] and active_workflow is None:
        return None
    return {
        "status": {
            **status,
            "active_workflow": None if active_workflow is None else active_workflow.get("target"),
        },
        "next_action": next_action(paths),
    }


def _active_payload(*, intent: str, active: dict[str, Any]) -> dict[str, Any]:
    action = active["next_action"]
    target = action.get("target")
    target_ref = None
    if isinstance(target, dict) and target.get("id"):
        target_ref = {"type": _target_type(action), "id": str(target["id"])}
    return _payload(
        status="active_work_exists",
        mutated=False,
        result={
            "intent": intent,
            "project_initialized": True,
            "initialization": None,
            "created_ids": {},
            "target": target_ref,
            "receipt": None,
            "active_work": active["status"],
        },
        warnings=["Active work already exists; no Goal, Task, Evidence, or event was created."],
        next_actions=[
            _next_action(
                text="Resume the existing active work, or pass --new to start separate work explicitly.",
                command=str(action["command"]),
                target=target_ref,
            )
        ],
    )


def _record_start_receipt(paths: ProjectPaths, *, receipt: dict[str, Any]) -> tuple[str, str]:
    conn = connect_mutation(paths)
    try:
        evidence_id = record_inline_evidence(
            conn,
            evidence_type=START_RECEIPT_CONTRACT_VERSION,
            summary=json.dumps(receipt, ensure_ascii=False, sort_keys=True),
            context=f"start:{receipt['target']['id']}",
            command="pcl start",
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="work_started",
            entity_type="task",
            entity_id=str(receipt["target"]["id"]),
            payload={"evidence_id": evidence_id, "receipt": receipt},
        )
        conn.commit()
        return evidence_id, event_id
    finally:
        conn.close()


def _repository_revision(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        return None
    revision = completed.stdout.strip()
    return revision or None


def _target_type(action: dict[str, Any]) -> str:
    action_type = str(action.get("type", ""))
    if "task" in action_type:
        return "task"
    if "defect" in action_type:
        return "defect"
    if "workflow" in action_type or "job" in action_type:
        return "workflow_run"
    return "goal"


def _next_action(*, text: str, command: str | None, target: dict[str, str] | None) -> dict[str, Any]:
    return {"text": text, "command": command, "target": target}


def _payload(
    *,
    status: str,
    mutated: bool,
    result: dict[str, Any],
    next_actions: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": START_CONTRACT_VERSION,
        "command": "start",
        "status": status,
        "mutated": mutated,
        "result": result,
        "warnings": warnings or [],
        "next_actions": next_actions,
    }
