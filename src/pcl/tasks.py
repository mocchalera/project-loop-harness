from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from .db import connect, connect_mutation
from .errors import InvalidInputError, TaskTerminalReadinessError
from .evidence import (
    ADHOC_EVIDENCE_TYPES,
    EvidenceAddError,
    assess_adhoc_evidence,
    newest_linked_evidence_id,
    require_healthy_terminal_evidence,
    superseding_evidence_id,
)
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .target_resolver import (
    TaskGoalTargetNotFoundError,
    resolve_routing_target,
)
from .terminal_readiness import (
    canonical_terminal_readiness_input_sha256,
    task_terminal_readiness,
)
from .timeutil import utc_now_iso
from .validation_projection import (
    finding_is_in_scope,
    finding_must_remain_visible,
)
from .validators import (
    ValidationFinding,
    collect_lifecycle_findings,
    collect_terminal_readiness_findings,
)


TASK_STATUSES = {"todo", "ready", "in_progress", "blocked", "done", "cancelled", "waived"}
TASK_RISKS = {"low", "medium", "high"}
COMPLETED_DEPENDENCY_STATUSES = {"done", "cancelled", "waived"}

TASK_COLUMNS = (
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
TASK_FIELDS = ", ".join(TASK_COLUMNS)
QUALIFIED_TASK_FIELDS = ", ".join(f"tasks.{column}" for column in TASK_COLUMNS)


def create_task(
    paths: ProjectPaths,
    *,
    title: str,
    description: str = "",
    priority: int = 100,
    owner: str = "",
    risk: str | None = None,
    effort: str = "",
    goal_id: str | None = None,
    feature_id: str | None = None,
    defect_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    conn = connect_mutation(paths)
    try:
        row = create_task_in_transaction(
            conn,
            paths,
            title=title,
            description=description,
            priority=priority,
            owner=owner,
            risk=risk,
            effort=effort,
            goal_id=goal_id,
            feature_id=feature_id,
            defect_id=defect_id,
        )
        conn.commit()
        return {"ok": True, **row}
    finally:
        conn.close()


def create_task_in_transaction(
    conn,
    paths: ProjectPaths,
    *,
    title: str,
    description: str = "",
    priority: int = 100,
    owner: str = "",
    risk: str | None = None,
    effort: str = "",
    goal_id: str | None = None,
    feature_id: str | None = None,
    defect_id: str | None = None,
    status: str = "todo",
) -> dict[str, Any]:
    """Insert one Task and event into the caller-owned mutation transaction."""

    _require_text(title, "--title is required to create a task.")
    risk = _clean_optional(risk)
    if risk is not None:
        _require_task_risk(risk)
    _require_task_status(status)
    _validate_optional_identifier(goal_id, "goal_id")
    _validate_optional_identifier(feature_id, "feature_id")
    _validate_optional_identifier(defect_id, "defect_id")
    now = utc_now_iso()

    if goal_id:
        _get_entity(conn, "goals", goal_id, "Goal", "goal_id")
    if feature_id:
        _get_entity(conn, "features", feature_id, "Feature", "feature_id")
    if defect_id:
        _get_entity(conn, "defects", defect_id, "Defect", "defect_id")
    task_id = next_prefixed_id(conn, "tasks", "T")
    row = {
        "id": task_id,
        "title": title.strip(),
        "description": description.strip(),
        "status": status,
        "priority": int(priority),
        "owner": _clean_optional(owner),
        "risk": risk,
        "effort": _clean_optional(effort),
        "related_goal_id": _clean_optional(goal_id),
        "related_feature_id": _clean_optional(feature_id),
        "related_defect_id": _clean_optional(defect_id),
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO tasks(
          id, title, description, status, priority, owner, risk, effort,
          related_goal_id, related_feature_id, related_defect_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["title"],
            row["description"],
            row["status"],
            row["priority"],
            row["owner"],
            row["risk"],
            row["effort"],
            row["related_goal_id"],
            row["related_feature_id"],
            row["related_defect_id"],
            row["created_at"],
            row["updated_at"],
        ),
    )
    append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type="task_created",
        entity_type="task",
        entity_id=task_id,
        payload={
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "owner": row["owner"],
            "risk": row["risk"],
            "effort": row["effort"],
            "related_goal_id": row["related_goal_id"],
            "related_feature_id": row["related_feature_id"],
            "related_defect_id": row["related_defect_id"],
        },
    )
    return row


def list_tasks(
    paths: ProjectPaths,
    *,
    status: str | None = None,
    goal_id: str | None = None,
    owner: str | None = None,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if status:
        _require_task_status(status)
    _validate_optional_identifier(goal_id, "goal_id")

    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if goal_id:
        clauses.append("related_goal_id = ?")
        params.append(goal_id)
    if owner:
        clauses.append("owner = ?")
        params.append(owner.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN")
        rows = conn.execute(
            f"""
            SELECT {TASK_FIELDS}
            FROM tasks
            {where}
            ORDER BY priority, id
            """,
            tuple(params),
        ).fetchall()
        tasks = [dict(row) for row in rows]
        for task in tasks:
            _attach_task_derived_status(paths, conn, task)
        return tasks
    finally:
        conn.close()


def read_task(paths: ProjectPaths, task_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN")
        try:
            target = resolve_routing_target(
                conn,
                task_id,
                expected_type="task",
            )
        except TaskGoalTargetNotFoundError as exc:
            raise InvalidInputError(
                f"Task does not exist: {task_id}",
                details={"task_id": task_id},
            ) from exc
        task = dict(target.row)
        task["dependencies"] = _related_tasks(conn, task_id, direction="dependencies")
        task["dependents"] = _related_tasks(conn, task_id, direction="dependents")
        _attach_task_terminal_readiness(paths, conn, task)
        return task
    finally:
        conn.close()


def set_task_status(paths: ProjectPaths, task_id: str, *, status: str, reason: str) -> dict[str, Any]:
    require_initialized(
        paths,
        allowed_error_codes=frozenset(
            {"config_dashboard_auto_render_invalid"}
        ),
    )
    _validate_identifier(task_id, "task_id")
    _require_task_status(status)
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        task = _get_task(conn, task_id)
        previous_status = str(task["status"])
        if previous_status == status:
            return {
                "ok": True,
                "id": task_id,
                "from_status": previous_status,
                "to_status": status,
                "status": status,
                "changed": False,
                "evidence_recorded": False,
            }
        _require_text(reason, "--reason is required to update task status.")
        readiness = None
        if status == "done":
            readiness = task_terminal_readiness_for_row(
                paths,
                conn,
                dict(task),
                source="task_status",
            )
            if not readiness["terminal_allowed"]:
                raise TaskTerminalReadinessError(
                    task_id=task_id,
                    readiness=readiness,
                )
        conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, now, task_id))
        cleaned_reason = reason.strip()
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_status_changed",
            entity_type="task",
            entity_id=task_id,
            payload={
                "from_status": previous_status,
                "to_status": status,
                "reason": cleaned_reason,
                **(
                    {"terminal_readiness": readiness}
                    if readiness is not None
                    else {}
                ),
            },
        )
        conn.commit()
        result = {
            "ok": True,
            "id": task_id,
            "from_status": previous_status,
            "to_status": status,
            "reason": cleaned_reason,
            "changed": True,
        }
        if readiness is not None:
            result["terminal_readiness"] = readiness
        return result
    finally:
        conn.close()


def add_dependency(paths: ProjectPaths, task_id: str, *, depends_on_task_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    _validate_identifier(depends_on_task_id, "depends_on_task_id")
    now = utc_now_iso()

    conn = connect_mutation(paths)
    try:
        _get_task(conn, task_id)
        _get_task(conn, depends_on_task_id)
        if task_id == depends_on_task_id:
            raise InvalidInputError(
                "Task cannot depend on itself.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        if _dependency_exists(conn, task_id, depends_on_task_id):
            raise InvalidInputError(
                f"Task {task_id} already depends on {depends_on_task_id}.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        if _would_create_cycle(conn, task_id, depends_on_task_id):
            raise InvalidInputError(
                f"Task dependency would create a cycle: {task_id} -> {depends_on_task_id}.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        conn.execute(
            """
            INSERT INTO task_dependencies(task_id, depends_on_task_id, created_at)
            VALUES (?, ?, ?)
            """,
            (task_id, depends_on_task_id, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_dependency_added",
            entity_type="task",
            entity_id=task_id,
            payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
        )
        conn.commit()
        return {"ok": True, "task_id": task_id, "depends_on_task_id": depends_on_task_id}
    finally:
        conn.close()


def remove_dependency(paths: ProjectPaths, task_id: str, *, depends_on_task_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    _validate_identifier(depends_on_task_id, "depends_on_task_id")

    conn = connect_mutation(paths)
    try:
        _get_task(conn, task_id)
        _get_task(conn, depends_on_task_id)
        if not _dependency_exists(conn, task_id, depends_on_task_id):
            raise InvalidInputError(
                f"Task {task_id} does not depend on {depends_on_task_id}.",
                details={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
        conn.execute(
            "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on_task_id = ?",
            (task_id, depends_on_task_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="task_dependency_removed",
            entity_type="task",
            entity_id=task_id,
            payload={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
        )
        conn.commit()
        return {"ok": True, "task_id": task_id, "depends_on_task_id": depends_on_task_id}
    finally:
        conn.close()


def _get_task(conn, task_id: str):
    row = conn.execute(
        f"""
        SELECT {TASK_FIELDS}
        FROM tasks
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Task does not exist: {task_id}",
            details={"task_id": task_id},
        )
    return row


def task_terminal_readiness_for_row(
    paths: ProjectPaths,
    conn,
    task: Mapping[str, Any],
    *,
    source: str = "task_read",
) -> dict[str, Any]:
    task_id = str(task["id"])
    resolved = resolve_routing_target(
        conn,
        task_id,
        expected_type="task",
    )
    current_task = dict(resolved.row)
    feature_id = str(current_task.get("related_feature_id") or "").strip() or None
    dependencies = [
        dict(row)
        for row in conn.execute(
            """
            SELECT tasks.id, tasks.status
            FROM task_dependencies
            JOIN tasks ON tasks.id = task_dependencies.depends_on_task_id
            WHERE task_dependencies.task_id = ?
            ORDER BY tasks.id
            """,
            (task_id,),
        ).fetchall()
    ]
    feature: dict[str, Any] | None = None
    stories: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    workflow_runs: list[dict[str, Any]] = []
    workflow_jobs: list[dict[str, Any]] = []
    workflow_verifications: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    current_proof_refs: set[tuple[str, str]] = set(resolved.scope_refs)

    incomplete_dependencies = [
        row
        for row in dependencies
        if row["status"] not in COMPLETED_DEPENDENCY_STATUSES
    ]
    if incomplete_dependencies:
        requirements.append(
            {
                "code": "task_done_dependency_incomplete",
                "state": "incomplete",
                "message": f"Task {task_id} has incomplete dependencies.",
                "next_command": (
                    f"pcl task read {incomplete_dependencies[0]['id']} --json"
                ),
                "details": {
                    "task_id": task_id,
                    "dependencies": incomplete_dependencies,
                },
            }
        )

    if feature_id is not None:
        feature_row = conn.execute(
            "SELECT * FROM features WHERE id = ?",
            (feature_id,),
        ).fetchone()
        if feature_row is None:
            requirements.append(
                {
                    "code": "task_done_feature_missing",
                    "state": "blocked",
                    "message": f"Task {task_id} references missing Feature {feature_id}.",
                    "next_command": f"pcl task read {task_id} --json",
                    "details": {"task_id": task_id, "feature_id": feature_id},
                }
            )
        else:
            feature = dict(feature_row)
            if feature["status"] != "done":
                requirements.append(
                    {
                        "code": "task_done_feature_not_terminal",
                        "state": "blocked",
                        "message": (
                            f"Feature {feature_id} is {feature['status']}, not done."
                        ),
                        "next_command": f"pcl feature read {feature_id} --json",
                        "details": {
                            "feature_id": feature_id,
                            "status": str(feature["status"]),
                        },
                    }
                )
        stories = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM user_stories
                WHERE feature_id = ?
                ORDER BY id
                """,
                (feature_id,),
            ).fetchall()
        ]
        tests = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM test_cases
                WHERE feature_id = ?
                ORDER BY id
                """,
                (feature_id,),
            ).fetchall()
        ]
        defects = [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM defects
                WHERE feature_id = ?
                ORDER BY id
                """,
                (feature_id,),
            ).fetchall()
        ]
        if feature is not None and feature["status"] == "done":
            acceptance_evidence_id = newest_linked_evidence_id(
                conn,
                target_type="feature",
                target_id=feature_id,
                link_role="acceptance",
            )
            try:
                if acceptance_evidence_id is None:
                    raise EvidenceAddError(
                        f"Feature {feature_id} has no acceptance Evidence.",
                        code="feature_done_evidence_required",
                        details={
                            "feature_id": feature_id,
                            "reason": "missing_target_bound_evidence",
                        },
                    )
                evidence_row = require_healthy_terminal_evidence(
                    paths,
                    conn,
                    evidence_id=acceptance_evidence_id,
                    error_code="feature_done_evidence_required",
                    allowed_types=ADHOC_EVIDENCE_TYPES,
                )
                evidence_rows.append(dict(evidence_row))
                current_proof_refs.add(("evidence", acceptance_evidence_id))
            except EvidenceAddError as exc:
                requirements.append(
                    {
                        "code": "feature_done_evidence_required",
                        "state": "blocked",
                        "message": str(exc),
                        "next_command": f"pcl feature read {feature_id} --json",
                        "requires_human": exc.details.get("reason")
                        in {"wrong_evidence_type", "missing_evidence"},
                        "details": dict(exc.details),
                    }
                )

        for test in tests:
            evidence_id = str(test.get("evidence_id") or "").strip()
            if evidence_id:
                current_proof_refs.add(("evidence", evidence_id))
                evidence_row = conn.execute(
                    "SELECT * FROM evidence WHERE id = ?",
                    (evidence_id,),
                ).fetchone()
                if evidence_row is not None:
                    evidence_rows.append(dict(evidence_row))
            run_id = str(test.get("last_run_id") or "").strip()
            if test["status"] != "passing" or not run_id:
                continue
            run_row = conn.execute(
                "SELECT * FROM workflow_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                requirements.append(
                    {
                        "code": "task_terminal_workflow_run_missing",
                        "state": "blocked",
                        "message": (
                            f"Passing Test {test['id']} references missing Workflow Run "
                            f"{run_id}."
                        ),
                        "next_command": f"pcl test read {test['id']} --json",
                        "details": {"test_case_id": str(test["id"]), "run_id": run_id},
                    }
                )
                continue
            run = dict(run_row)
            workflow_runs.append(run)
            if run.get("goal_id") != resolved.goal_id:
                requirements.append(
                    {
                        "code": "task_terminal_workflow_goal_mismatch",
                        "state": "blocked",
                        "message": (
                            f"Workflow Run {run_id} does not belong to Task {task_id}'s "
                            "Goal."
                        ),
                        "next_command": f"pcl run read {run_id} --json",
                        "details": {
                            "task_id": task_id,
                            "task_goal_id": resolved.goal_id,
                            "run_id": run_id,
                            "run_goal_id": run.get("goal_id"),
                        },
                    }
                )
            if run["status"] != "passed":
                requirements.append(
                    {
                        "code": "task_terminal_workflow_run_incomplete",
                        "state": "incomplete",
                        "message": f"Workflow Run {run_id} is {run['status']}, not passed.",
                        "next_command": f"pcl run read {run_id} --json",
                        "details": {"run_id": run_id, "status": str(run["status"])},
                    }
                )
            jobs = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM agent_jobs WHERE workflow_run_id = ? ORDER BY id",
                    (run_id,),
                ).fetchall()
            ]
            verifications = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM verifications
                    WHERE workflow_run_id = ?
                    ORDER BY created_at, id
                    """,
                    (run_id,),
                ).fetchall()
            ]
            workflow_jobs.extend(jobs)
            workflow_verifications.extend(verifications)
            bad_jobs = [row for row in jobs if row["status"] != "passed"]
            if not jobs or bad_jobs:
                requirements.append(
                    {
                        "code": "workflow_run_passed_jobs_incomplete",
                        "state": "blocked",
                        "message": f"Workflow Run {run_id} has non-passed Jobs.",
                        "next_command": f"pcl run read {run_id} --json",
                        "requires_human": True,
                        "details": {
                            "run_id": run_id,
                            "jobs": jobs,
                            "non_passed_jobs": bad_jobs,
                        },
                    }
                )
            approved = [
                row for row in verifications if row["result"] == "approved"
            ]
            if not approved:
                requirements.append(
                    {
                        "code": "workflow_run_passed_verification_missing",
                        "state": "blocked",
                        "message": (
                            f"Workflow Run {run_id} has no approved Verification."
                        ),
                        "next_command": f"pcl run read {run_id} --json",
                        "requires_human": True,
                        "details": {"run_id": run_id},
                    }
                )

    goal = dict(resolved.goal_row) if resolved.goal_row is not None else None
    decisions: list[dict[str, Any]] = []
    escalations: list[dict[str, Any]] = []
    if goal is not None:
        if goal["status"] in {"closed", "cancelled"}:
            requirements.append(
                {
                    "code": "task_terminal_goal_contradiction",
                    "state": "blocked",
                    "message": (
                        f"Task {task_id} is active under terminal Goal {goal['id']} "
                        f"({goal['status']})."
                    ),
                    "next_command": f"pcl goal read {goal['id']} --json",
                    "requires_human": True,
                    "details": {
                        "goal_id": str(goal["id"]),
                        "goal_status": str(goal["status"]),
                    },
                }
            )
        try:
            budget = json.loads(str(goal.get("budget_json") or "{}"))
        except json.JSONDecodeError:
            budget = None
        if not isinstance(budget, dict):
            requirements.append(
                {
                    "code": "task_terminal_goal_budget_unknown",
                    "state": "blocked",
                    "message": f"Goal {goal['id']} budget state is not a JSON object.",
                    "next_command": f"pcl goal read {goal['id']} --json",
                    "requires_human": True,
                    "details": {"goal_id": str(goal["id"])},
                }
            )
        elif budget.get("exhausted") is True:
            requirements.append(
                {
                    "code": "task_terminal_goal_budget_exhausted",
                    "state": "blocked",
                    "message": f"Goal {goal['id']} budget is exhausted.",
                    "next_command": f"pcl goal read {goal['id']} --json",
                    "details": {"goal_id": str(goal["id"])},
                }
            )
        escalations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT escalations.*
                FROM escalations
                JOIN workflow_runs ON workflow_runs.id = escalations.workflow_run_id
                WHERE escalations.status = 'open' AND workflow_runs.goal_id = ?
                ORDER BY escalations.id
                """,
                (goal["id"],),
            ).fetchall()
        ]
        if escalations:
            requirements.append(
                {
                    "code": "task_terminal_escalation_open",
                    "state": "blocked",
                    "message": f"Goal {goal['id']} has open Escalations.",
                    "next_command": "pcl escalation list --status open --json",
                    "requires_human": True,
                    "details": {"escalations": escalations},
                }
            )

    for row in conn.execute(
        "SELECT * FROM decisions WHERE status = 'open' ORDER BY id"
    ).fetchall():
        if resolved.decision_blocks(row["blocks_json"]):
            decisions.append(dict(row))
    if decisions:
        requirements.append(
            {
                "code": "task_terminal_decision_open",
                "state": "blocked",
                "message": f"Task {task_id} has open blocking Decisions.",
                "next_command": "pcl decision list --status open --json",
                "requires_human": True,
                "details": {"decisions": decisions},
            }
        )

    lifecycle_findings = collect_lifecycle_findings(paths, conn)
    for finding in lifecycle_findings:
        if (finding.entity_type, finding.entity_id) not in current_proof_refs:
            continue
        requirements.append(
            {
                "code": finding.code,
                "state": "blocked",
                "message": finding.message,
                "next_command": f"pcl task read {task_id} --json",
                "details": {
                    "entity": {
                        "type": finding.entity_type,
                        "id": finding.entity_id,
                    },
                    "current_proof": True,
                    **finding.details,
                },
            }
        )

    findings = collect_terminal_readiness_findings(paths, conn)
    for finding in findings:
        requirement = _readiness_requirement_for_finding(
            finding,
            resolved=resolved,
            current_proof_refs=current_proof_refs,
        )
        if requirement is not None:
            requirements.append(requirement)

    evidence_assessments: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        SELECT id, type, path
        FROM evidence
        WHERE type IN ('adhoc_artifact', 'adhoc_bundle')
        ORDER BY id
        """
    ).fetchall():
        evidence_id = str(row["id"])
        assessment = assess_adhoc_evidence(
            paths,
            evidence_id=evidence_id,
            evidence_type=str(row["type"]),
            manifest_path_value=str(row["path"] or ""),
            validate_optional_fields=True,
        )
        if assessment["health"] == "ok":
            continue
        superseded_by = superseding_evidence_id(conn, evidence_id)
        historical = superseded_by is not None
        in_current_proof = ("evidence", evidence_id) in current_proof_refs
        evidence_assessments.append(
            {
                "evidence_id": evidence_id,
                "assessment": assessment,
                "superseded_by": superseded_by,
            }
        )
        for finding in assessment.get("findings", []):
            normalized_finding = (
                dict(finding)
                if isinstance(finding, Mapping)
                else {"code": "assessment_finding_invalid"}
            )
            code = str(
                normalized_finding.get("code")
                or "assessment_finding_invalid"
            )
            requirements.append(
                {
                    "code": f"evidence_adhoc_{code}",
                    "state": (
                        "blocked"
                        if not historical or in_current_proof
                        else "advisory"
                    ),
                    "message": (
                        f"Adhoc Evidence {evidence_id} failed current health "
                        f"assessment: {code}."
                    ),
                    "next_command": f"pcl evidence show {evidence_id} --json",
                    "requires_human": code
                    in {
                        "contract_version_unsupported",
                        "assessment_finding_invalid",
                    },
                    "details": {
                        "evidence_id": evidence_id,
                        "finding": normalized_finding,
                        "proof_scope": (
                            "historical" if historical else "active"
                        ),
                        "current_proof": in_current_proof,
                        "superseded_by": superseded_by,
                    },
                }
            )

    hwm_row = conn.execute(
        "SELECT sequence, id FROM events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    hwm = {
        "sequence": int(hwm_row["sequence"]) if hwm_row is not None else 0,
        "event_id": str(hwm_row["id"]) if hwm_row is not None else None,
    }
    canonical_input = {
        "task": current_task,
        "dependencies": dependencies,
        "feature": feature,
        "stories": stories,
        "tests": tests,
        "defects": defects,
        "goal": goal,
        "decisions": decisions,
        "escalations": escalations,
        "workflow_runs": sorted(workflow_runs, key=lambda row: str(row["id"])),
        "workflow_jobs": sorted(workflow_jobs, key=lambda row: str(row["id"])),
        "workflow_verifications": sorted(
            workflow_verifications,
            key=lambda row: str(row["id"]),
        ),
        "evidence": sorted(
            {str(row["id"]): row for row in evidence_rows}.values(),
            key=lambda row: str(row["id"]),
        ),
        "findings": [finding.to_dict() for finding in findings],
        "lifecycle_findings": [
            {
                "code": finding.code,
                "message": finding.message,
                "entity_type": finding.entity_type,
                "entity_id": finding.entity_id,
                "details": finding.details,
            }
            for finding in lifecycle_findings
        ],
        "evidence_assessments": evidence_assessments,
        "event_hwm": hwm,
    }
    return task_terminal_readiness(
        task_id=task_id,
        task_status=str(current_task["status"]),
        feature_id=feature_id,
        stories=stories,
        tests=tests,
        defects=defects,
        additional_requirements=requirements,
        evaluation={
            "source": source,
            "evaluated_through_event_sequence": hwm["sequence"],
            "evaluated_through_event_id": hwm["event_id"],
            "input_sha256": canonical_terminal_readiness_input_sha256(
                canonical_input
            ),
            "finding_counts": {
                "active": sum(
                    finding.proof_scope == "active" for finding in findings
                ),
                "historical": sum(
                    finding.proof_scope == "historical" for finding in findings
                ),
            },
        },
    )


def _readiness_requirement_for_finding(
    finding: ValidationFinding,
    *,
    resolved,
    current_proof_refs: set[tuple[str, str]],
) -> dict[str, Any] | None:
    refs: set[tuple[str, str]] = set()
    if isinstance(finding.entity, dict):
        refs.add(
            (
                str(finding.entity.get("type") or ""),
                str(finding.entity.get("id") or ""),
            )
        )
    refs.update(
        (
            str(item.get("type") or ""),
            str(item.get("id") or ""),
        )
        for item in finding.related
        if isinstance(item, dict)
    )
    in_current_proof = bool(refs & current_proof_refs)
    if finding.proof_scope == "historical":
        state = "blocked" if in_current_proof else "advisory"
    elif finding_is_in_scope(finding, resolved) or finding_must_remain_visible(finding):
        state = (
            "blocked"
            if (
                finding.severity == "error"
                or finding.requires_human
                or finding.repair_class == "unsupported"
            )
            else "risk"
        )
    else:
        return None
    next_command = (
        finding.suggested_commands[0]
        if finding.suggested_commands
        else None
    )
    return {
        "code": finding.code,
        "state": state,
        "message": finding.message,
        "next_command": next_command,
        "requires_human": finding.requires_human,
        "details": {
            "entity": finding.entity,
            "related": finding.related,
            "proof_scope": finding.proof_scope,
            "repair_class": finding.repair_class,
            "current_proof": in_current_proof,
        },
    }


def _attach_task_terminal_readiness(
    paths: ProjectPaths,
    conn,
    task: dict[str, Any],
) -> None:
    readiness = task_terminal_readiness_for_row(paths, conn, task)
    task["terminal_readiness"] = readiness
    task["derived_status"] = readiness["derived_task_status"]


def _attach_task_derived_status(
    paths: ProjectPaths,
    conn,
    task: dict[str, Any],
) -> None:
    readiness = task_terminal_readiness_for_row(paths, conn, task)
    task["terminal_readiness"] = readiness
    task["derived_status"] = readiness["derived_task_status"]


def _get_entity(conn, table: str, entity_id: str, label: str, field_name: str):
    row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        raise InvalidInputError(
            f"{label} does not exist: {entity_id}",
            details={field_name: entity_id},
        )
    return row


def _related_tasks(conn, task_id: str, *, direction: str) -> list[dict[str, Any]]:
    if direction == "dependencies":
        join_column = "depends_on_task_id"
        source_column = "task_id"
    else:
        join_column = "task_id"
        source_column = "depends_on_task_id"
    rows = conn.execute(
        f"""
        SELECT {QUALIFIED_TASK_FIELDS}
        FROM task_dependencies
        JOIN tasks ON tasks.id = task_dependencies.{join_column}
        WHERE task_dependencies.{source_column} = ?
        ORDER BY tasks.priority, tasks.id
        """,
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _dependency_exists(conn, task_id: str, depends_on_task_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM task_dependencies
        WHERE task_id = ? AND depends_on_task_id = ?
        """,
        (task_id, depends_on_task_id),
    ).fetchone()
    return row is not None


def _would_create_cycle(conn, task_id: str, depends_on_task_id: str) -> bool:
    stack = [depends_on_task_id]
    seen: set[str] = set()
    while stack:
        current_id = stack.pop()
        if current_id == task_id:
            return True
        if current_id in seen:
            continue
        seen.add(current_id)
        rows = conn.execute(
            """
            SELECT depends_on_task_id
            FROM task_dependencies
            WHERE task_id = ?
            ORDER BY depends_on_task_id
            """,
            (current_id,),
        ).fetchall()
        stack.extend(str(row["depends_on_task_id"]) for row in rows)
    return False


def _require_task_status(status: str) -> None:
    if status not in TASK_STATUSES:
        raise InvalidInputError(
            f"Invalid task status: {status}",
            details={"status": status, "allowed": sorted(TASK_STATUSES)},
        )


def _require_task_risk(risk: str) -> None:
    if risk not in TASK_RISKS:
        raise InvalidInputError(
            f"Invalid task risk: {risk}",
            details={"risk": risk, "allowed": sorted(TASK_RISKS)},
        )


def _require_text(value: str, message: str) -> None:
    if not value.strip():
        raise InvalidInputError(message)


def _validate_optional_identifier(value: str | None, field_name: str) -> None:
    if value:
        _validate_identifier(value, field_name)


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
