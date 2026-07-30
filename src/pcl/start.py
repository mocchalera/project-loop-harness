from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from .commands import active_workflow_next_action, loop_status, next_action
from .command_domain import create_goal_in_transaction
from .db import connect, connect_mutation
from .direct_setup import _require_bound_root, commit_direct_setup
from .direct_spec import DirectSpecDocument, load_direct_spec
from .evidence import (
    EXECUTION_PROVENANCE_CONTRACT_VERSION,
    EXECUTION_PROVENANCE_EVIDENCE_TYPE,
    EXECUTION_PROVENANCE_LINK_ROLE,
    canonical_provenance_bytes,
    execution_provenance_document,
    insert_evidence_link,
    inspect_skill_files,
    preflight_provenance_destination,
    public_skill_entries,
    record_inline_evidence,
    write_provenance_artifact,
)
from .events import append_event
from .errors import (
    DataStoreError,
    DirectSpecError,
    InvalidInputError,
    ProjectNotInitializedError,
    ProjectValidationError,
)
from .ids import next_prefixed_id
from .init_project import init_project, plan_init_project
from .paths import ProjectPaths
from .project_config import finish_check_configuration_warning
from .mutation_tail import apply_direct_setup_tail
from .target_resolver import (
    TaskGoalTargetNotFoundError,
    resolve_routing_target,
)
from .start_retry import (
    build_start_request_identity,
    load_compatible_start_retry,
)
from .tasks import create_task_in_transaction
from .timeutil import utc_now_iso
from .validators import validate_project


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
    skills: list[str] | None = None,
    goal_id: str | None = None,
    task_id: str | None = None,
    direct_spec_path: str | None = None,
) -> dict[str, Any]:
    if not intent.strip():
        raise InvalidInputError("intent must not be empty.", details={"field": "intent"})
    if goal_id and task_id:
        raise InvalidInputError(
            "Choose only one of --goal or --task.",
            details={"goal": goal_id, "task": task_id},
        )
    if new and (goal_id or task_id):
        raise InvalidInputError(
            "--new cannot be combined with --goal or --task.",
            details={"new": True, "goal": goal_id, "task": task_id},
        )
    if direct_spec_path is not None:
        return _start_direct_work(
            paths,
            intent=intent,
            direct_spec_path=direct_spec_path,
            dry_run=dry_run,
            no_init=no_init,
            new=new,
            skills=skills or [],
            goal_id=goal_id,
            task_id=task_id,
        )

    planned_skills = inspect_skill_files(paths, skills or [])
    initialized = paths.db_path.is_file()
    if (goal_id or task_id) and not initialized:
        raise ProjectNotInitializedError(root=str(paths.root))
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

    if initialized and not new and not (goal_id or task_id):
        active = _active_work(paths)
        if active is not None:
            return _active_payload(intent=intent, active=active)

    if dry_run:
        target, planned_entities = _plan_start_target(
            paths,
            intent=intent,
            initialized=initialized,
            goal_id=goal_id,
            task_id=task_id,
        )
        return _payload(
            status="planned",
            mutated=False,
            result={
                "intent": intent,
                "project_initialized": initialized,
                "initialization": None if init_plan is None else init_plan.to_dict(),
                "planned_entities": planned_entities,
                "created_ids": {},
                "target": target,
                "receipt": None,
                "planned_provenance": public_skill_entries(planned_skills),
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

    started = _commit_start(
        paths,
        intent=intent,
        goal_id=goal_id,
        task_id=task_id,
        planned_skills=planned_skills,
    )
    selected_task_id = str(started["task_id"])
    action = next_action(paths, target=selected_task_id)

    finish_warning = finish_check_configuration_warning(paths.root)
    result = {
        "intent": intent,
        "project_initialized": project_initialized,
        "initialization": None if init_plan is None else init_plan.to_dict(),
        "created_ids": started["created_ids"],
        "target": {"type": "task", "id": selected_task_id},
        "receipt": started["receipt"],
        "provenance": started["provenance"],
    }
    if started["idempotent"]:
        result["idempotent"] = True
        result["reused_ids"] = started["reused_ids"]
    return _payload(
        status="already_started" if started["idempotent"] else "started",
        mutated=not started["idempotent"],
        result=result,
        next_actions=[
            _next_action(
                text="Review the task context and begin the requested work.",
                command=str(action["command"]),
                target={"type": "task", "id": selected_task_id},
            )
        ],
        warnings=[] if finish_warning is None else [finish_warning],
    )


def _start_direct_work(
    paths: ProjectPaths,
    *,
    intent: str,
    direct_spec_path: str,
    dry_run: bool,
    no_init: bool,
    new: bool,
    skills: list[str],
    goal_id: str | None,
    task_id: str | None,
) -> dict[str, Any]:
    del no_init  # Direct Setup never initializes, so this flag is already its default.
    incompatible = {
        "--goal": goal_id,
        "--task": task_id,
        "--skill": skills or None,
    }
    selected = sorted(flag for flag, value in incompatible.items() if value)
    if selected:
        raise DirectSpecError(
            "--direct-spec cannot be combined with attach or Skill provenance flags.",
            code="direct_setup_option_conflict",
            details={"flags": selected},
        )
    if not paths.db_path.is_file():
        raise ProjectNotInitializedError(root=str(paths.root))
    spec = load_direct_spec(paths, direct_spec_path)
    try:
        return _start_loaded_direct_spec(
            paths,
            intent=intent,
            spec=spec,
            dry_run=dry_run,
            new=new,
        )
    finally:
        spec.close()


def _start_loaded_direct_spec(
    paths: ProjectPaths,
    *,
    intent: str,
    spec: DirectSpecDocument,
    dry_run: bool,
    new: bool,
) -> dict[str, Any]:
    authority_paths = spec.root_binding.bound_paths()
    _require_bound_root(spec, paths, phase="before_preflight_validation")
    validation = validate_project(authority_paths)
    _require_bound_root(spec, paths, phase="after_preflight_validation")
    blocking = [
        finding.message
        for finding in validation.findings
        if finding.severity == "error"
        and finding.code != "config_dashboard_auto_render_invalid"
    ]
    classified = {
        finding.message
        for finding in validation.findings
        if finding.severity == "error"
    }
    blocking.extend(error for error in validation.errors if error not in classified)
    if blocking:
        raise ProjectValidationError(
            errors=blocking,
            warnings=validation.warnings,
        )
    if dry_run:
        planned_entities = [
            {"type": "goal", "status": "open", "title": intent},
            {
                "type": "task",
                "status": "in_progress",
                "title": intent,
                "related_goal": "created_goal",
            },
            {
                "type": "feature",
                "status": "needs_test",
                **spec.value["feature"],
            },
            *(
                {
                    "type": "user_story",
                    "status": "draft",
                    "ref": story["ref"],
                }
                for story in spec.value["stories"]
            ),
            *(
                {
                    "type": "test_case",
                    "status": "planned",
                    "ref": test["ref"],
                    "story_ref": test["story_ref"],
                }
                for test in spec.value["tests"]
            ),
            {"type": "evidence", "contract_version": START_RECEIPT_CONTRACT_VERSION},
        ]
        return _payload(
            status="planned",
            mutated=False,
            result={
                "intent": intent,
                "project_initialized": False,
                "initialization": None,
                "planned_entities": planned_entities,
                "created_ids": {},
                "target": {"type": "task", "id": None},
                "receipt": None,
                "provenance": None,
                "direct_spec": {
                    "contract_version": spec.value["contract_version"],
                    "request_id": spec.request_id,
                    "raw_sha256": spec.raw_sha256,
                    "canonical_sha256": spec.canonical_sha256,
                },
                "requires_human": True,
                "human_actions": [],
            },
            next_actions=[
                _next_action(
                    text="Apply this Direct Setup plan by rerunning without --dry-run.",
                    command=None,
                    target=None,
                )
            ],
        )

    started = commit_direct_setup(
        paths,
        intent=intent,
        spec=spec,
        new=new,
        preflight_repository_revision=spec.root_binding.repository_revision(),
    )
    selected_task_id = str(started["task_id"])
    direct = started["receipt"]["direct_setup"]
    story_ids = list(direct["bundle_created_ids"]["stories"])
    result = {
        "intent": intent,
        "project_initialized": False,
        "initialization": None,
        "created_ids": started["created_ids"],
        "target": {"type": "task", "id": selected_task_id},
        "receipt": started["receipt"],
        "provenance": None,
        "repository_revision": started["repository_revision"],
        "requires_human": True,
        "human_actions": [_direct_story_action(story_id) for story_id in story_ids],
    }
    if started["idempotent"]:
        result["idempotent"] = True
        result["reused_ids"] = started["reused_ids"]
    payload = _payload(
        status="already_started" if started["idempotent"] else "started",
        mutated=not started["idempotent"],
        result=result,
        next_actions=[
            _next_action(
                text=(
                    "Review the draft Stories through an authenticated human decision "
                    "channel, then begin the requested work."
                ),
                command=None,
                target={"type": "task", "id": selected_task_id},
            )
        ],
        warnings=[],
    )
    return apply_direct_setup_tail(
        authority_paths,
        payload,
        target_id=selected_task_id,
        changed=not started["idempotent"],
    )


def _direct_story_action(story_id: str) -> dict[str, Any]:
    return {
        "action_kind": "review_story",
        "target": {"type": "user_story", "id": story_id},
        "requires_human": True,
        "reason": (
            "Story approval was not supplied by an authenticated human decision "
            "channel and is not inferred."
        ),
        "expected_after": (
            "A human separately decides whether the Story should be approved or waived."
        ),
        "command": None,
    }


def _plan_start_target(
    paths: ProjectPaths,
    *,
    intent: str,
    initialized: bool,
    goal_id: str | None,
    task_id: str | None,
) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    if not initialized or not (goal_id or task_id):
        return (
            {"type": "task", "id": None},
            [
                {"type": "goal", "status": "open", "title": intent},
                {
                    "type": "task",
                    "status": "in_progress",
                    "title": intent,
                    "related_goal": "created_goal",
                },
                {"type": "evidence", "contract_version": START_RECEIPT_CONTRACT_VERSION},
                {"type": "event", "event_type": "work_started"},
            ],
        )

    conn = connect(paths.db_path)
    try:
        if task_id:
            target = _resolve_start_target(conn, task_id, expected_type="task")
            _require_startable_target(target)
            planned = [
                {
                    "type": "task",
                    "id": target.id,
                    "status": "in_progress",
                    "operation": "attach",
                }
            ]
            selected_task_id: str | None = target.id
        else:
            target = _resolve_start_target(conn, str(goal_id), expected_type="goal")
            _require_startable_target(target)
            planned = [
                {
                    "type": "task",
                    "id": None,
                    "status": "in_progress",
                    "title": intent,
                    "related_goal": target.id,
                }
            ]
            selected_task_id = None
    finally:
        conn.close()
    planned.extend(
        [
            {"type": "evidence", "contract_version": START_RECEIPT_CONTRACT_VERSION},
            {"type": "event", "event_type": "work_started"},
        ]
    )
    return {"type": "task", "id": selected_task_id}, planned


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
                command=action.get("command"),
                target=target_ref,
            )
        ],
    )


def _commit_start(
    paths: ProjectPaths,
    *,
    intent: str,
    goal_id: str | None,
    task_id: str | None,
    planned_skills: list[dict[str, str]],
) -> dict[str, Any]:
    repository_revision = _repository_revision(paths.root)
    request_identity_sha256 = (
        build_start_request_identity(
            intent=intent,
            task_id=task_id,
            repository_revision=repository_revision,
            skills=planned_skills,
        )
        if task_id is not None
        else None
    )
    conn = connect_mutation(paths)
    artifact_path: Path | None = None
    try:
        created_domain_ids: dict[str, str] = {}
        if task_id:
            target = _resolve_start_target(conn, task_id, expected_type="task")
            _require_startable_target(target)
            selected_task_id = target.id
            if target.status == "in_progress":
                retry = load_compatible_start_retry(
                    paths,
                    conn,
                    task_id=selected_task_id,
                    request_identity_sha256=str(request_identity_sha256),
                    repository_revision=repository_revision,
                    skills=planned_skills,
                    receipt_contract_version=START_RECEIPT_CONTRACT_VERSION,
                )
                if retry is not None:
                    return {
                        "task_id": selected_task_id,
                        "created_ids": {},
                        "receipt": retry["receipt"],
                        "provenance": retry["provenance"],
                        "idempotent": True,
                        "reused_ids": retry["reused_ids"],
                    }
            if planned_skills:
                preflight_provenance_destination(paths)
            if target.status != "in_progress":
                now = utc_now_iso()
                conn.execute(
                    "UPDATE tasks SET status = 'in_progress', updated_at = ? WHERE id = ?",
                    (now, selected_task_id),
                )
                append_event(
                    conn=conn,
                    events_path=paths.events_path,
                    event_type="task_status_changed",
                    entity_type="task",
                    entity_id=selected_task_id,
                    payload={
                        "from_status": target.status,
                        "to_status": "in_progress",
                        "reason": "Explicitly attached by pcl start.",
                    },
                )
        elif goal_id:
            target = _resolve_start_target(conn, goal_id, expected_type="goal")
            _require_startable_target(target)
            task = create_task_in_transaction(
                conn,
                paths,
                title=intent,
                goal_id=target.id,
                status="in_progress",
            )
            selected_task_id = str(task["id"])
            created_domain_ids["task"] = selected_task_id
            if planned_skills:
                preflight_provenance_destination(paths)
        else:
            selected_goal_id = create_goal_in_transaction(
                conn,
                paths,
                title=intent,
            )
            task = create_task_in_transaction(
                conn,
                paths,
                title=intent,
                goal_id=selected_goal_id,
                status="in_progress",
            )
            selected_task_id = str(task["id"])
            created_domain_ids.update(
                {"goal": selected_goal_id, "task": selected_task_id}
            )
            if planned_skills:
                preflight_provenance_destination(paths)

        receipt = {
            "contract_version": START_RECEIPT_CONTRACT_VERSION,
            "generated_at": utc_now_iso(),
            "intent": intent,
            "actor": START_ACTOR,
            "repository_revision": repository_revision,
            "created_ids": dict(created_domain_ids),
            "target": {"type": "task", "id": selected_task_id},
        }
        if request_identity_sha256 is not None:
            receipt["request_identity_sha256"] = request_identity_sha256
        evidence_id = record_inline_evidence(
            conn,
            evidence_type=START_RECEIPT_CONTRACT_VERSION,
            summary=json.dumps(receipt, ensure_ascii=False, sort_keys=True),
            context=f"start:{receipt['target']['id']}",
            command="pcl start",
        )
        provenance = None
        event_provenance = None
        if planned_skills:
            provenance_id = next_prefixed_id(conn, "evidence", "E")
            document = execution_provenance_document(
                skills=planned_skills,
                repository_revision=receipt["repository_revision"],
                task_id=str(receipt["target"]["id"]),
            )
            content = canonical_provenance_bytes(document)
            artifact_path, artifact_sha256 = write_provenance_artifact(
                paths, evidence_id=provenance_id, content=content,
            )
            relative_path = str(artifact_path.relative_to(paths.root))
            now = utc_now_iso()
            conn.execute(
                "INSERT INTO evidence(id, type, path, command, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (provenance_id, EXECUTION_PROVENANCE_EVIDENCE_TYPE, relative_path, "pcl start", f"Execution provenance for task {receipt['target']['id']} with {len(planned_skills)} Skill file(s).", now),
            )
            insert_evidence_link(
                conn, evidence_id=provenance_id, target_type="task",
                target_id=str(receipt["target"]["id"]), link_role=EXECUTION_PROVENANCE_LINK_ROLE,
                created_at=now,
            )
            event_provenance = {
                "evidence_id": provenance_id,
                "artifact_sha256": artifact_sha256,
                "contract_version": EXECUTION_PROVENANCE_CONTRACT_VERSION,
                "target": receipt["target"],
            }
            provenance = {**event_provenance, "path": relative_path}
        payload = {"evidence_id": evidence_id, "receipt": receipt}
        if event_provenance is not None:
            payload["execution_provenance"] = event_provenance
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="work_started",
            entity_type="task",
            entity_id=str(receipt["target"]["id"]),
            payload=payload,
        )
        conn.commit()
        created_ids = {
            **created_domain_ids,
            "evidence": evidence_id,
            "event": event_id,
        }
        if provenance is not None:
            created_ids["provenance_evidence"] = provenance["evidence_id"]
        return {
            "task_id": selected_task_id,
            "created_ids": created_ids,
            "receipt": {
                **receipt,
                "evidence_id": evidence_id,
                "event_id": event_id,
            },
            "provenance": provenance,
            "idempotent": False,
            "reused_ids": None,
        }
    except BaseException as exc:
        committed = bool(getattr(conn, "_authoritative_commit_completed", False))
        if not committed:
            try:
                conn.rollback()
            except BaseException:
                pass
            if artifact_path is not None:
                try:
                    artifact_path.unlink(missing_ok=True)
                except OSError:
                    pass
        if isinstance(exc, (OSError, sqlite3.Error)):
            raise DataStoreError(f"Could not record execution provenance: {exc}") from exc
        raise
    finally:
        conn.close()


def _resolve_start_target(conn, target_id: str, *, expected_type: str):
    try:
        return resolve_routing_target(
            conn,
            target_id,
            expected_type=expected_type,
        )
    except TaskGoalTargetNotFoundError as exc:
        raise InvalidInputError(
            f"Start target does not exist: {target_id}",
            details={"target": target_id, "target_type": exc.target_type},
        ) from exc


def _require_startable_target(target) -> None:
    allowed_statuses = (
        {"todo", "ready", "in_progress"}
        if target.type == "task"
        else {"open", "active"}
    )
    if target.status not in allowed_statuses:
        raise InvalidInputError(
            f"Cannot attach start to {target.type} {target.id} in status {target.status}.",
            details={
                "target": target.id,
                "target_type": target.type,
                "status": target.status,
            },
        )
    if (
        target.type == "task"
        and target.goal_row is not None
        and str(target.goal_row["status"]) not in {"open", "active"}
    ):
        raise InvalidInputError(
            f"Task {target.id} belongs to non-active Goal {target.goal_id}.",
            details={
                "target": target.id,
                "target_type": "task",
                "related_goal_id": target.goal_id,
                "related_goal_status": str(target.goal_row["status"]),
            },
        )


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
