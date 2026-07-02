from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import connect
from .errors import InvalidInputError
from .guards import require_initialized
from .links import enrich_decisions_with_links, enrich_escalations_with_links
from .paths import ProjectPaths
from .rubric import claims_rubric_v1
from .validators import validate_project


TASK_COMPLETED_DEPENDENCY_STATUSES = {"done", "cancelled", "waived"}
TASK_STATUS_ORDER = {
    "in_progress": 0,
    "ready": 1,
    "todo": 2,
    "blocked": 3,
    "done": 4,
    "waived": 5,
    "cancelled": 6,
}


def report_goal(paths: ProjectPaths, goal_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(goal_id, "goal_id")
    conn = connect(paths.db_path)
    try:
        goal = _one(conn, "SELECT * FROM goals WHERE id = ?", (goal_id,))
        if goal is None:
            raise InvalidInputError(f"Goal does not exist: {goal_id}", details={"goal_id": goal_id})
        runs = _rows(conn, "SELECT * FROM workflow_runs WHERE goal_id = ? ORDER BY started_at, id", (goal_id,))
        run_ids = [str(run["id"]) for run in runs]
        jobs = _jobs_for_runs(conn, run_ids)
        verifications = _verifications_for_runs(conn, run_ids)
        escalations = _escalations_for_runs(conn, run_ids)
        decisions = _decisions_for_escalations(conn, [str(escalation["id"]) for escalation in escalations])
        escalations = enrich_escalations_with_links(escalations, decisions)
        tasks = _tasks_for_goal(conn, goal_id)
        test_cases = _test_cases_for_runs(conn, run_ids)
        user_stories = _stories_for_test_cases(conn, test_cases)
        features = _features_for_test_cases(conn, test_cases)
        entities = [
            ("goal", goal_id),
            *[("workflow_run", run_id) for run_id in run_ids],
            *[("agent_job", job["id"]) for job in jobs],
            *[("verification", verification["id"]) for verification in verifications],
            *[("escalation", escalation["id"]) for escalation in escalations],
            *[("decision", decision["id"]) for decision in decisions],
            *[("task", task["id"]) for task in tasks],
            *[("feature", feature["id"]) for feature in features],
            *[("user_story", story["id"]) for story in user_stories],
            *[("test_case", test_case["id"]) for test_case in test_cases],
        ]
        events = _events_for_entities(conn, entities)
        evidence = _evidence_for_report(conn, events=events, jobs=jobs)
        data = {
            "kind": "goal",
            "id": goal_id,
            "goal": goal,
            "workflow_runs": runs,
            "agent_jobs": jobs,
            "verifications": verifications,
            "escalations": escalations,
            "decisions": decisions,
            "tasks": tasks,
            "features": features,
            "user_stories": user_stories,
            "test_cases": test_cases,
            "evidence": evidence,
            "events": events,
        }
    finally:
        conn.close()
    path = _report_path(paths, "goal", goal_id)
    markdown = _render_goal_report(data)
    _write_report(path, markdown)
    return {"ok": True, "kind": "goal", "id": goal_id, "path": str(path), "report": data}


def report_run(paths: ProjectPaths, workflow_run_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(workflow_run_id, "workflow_run_id")
    conn = connect(paths.db_path)
    try:
        run = _one(conn, "SELECT * FROM workflow_runs WHERE id = ?", (workflow_run_id,))
        if run is None:
            raise InvalidInputError(
                f"Workflow run does not exist: {workflow_run_id}",
                details={"workflow_run_id": workflow_run_id},
            )
        jobs = _jobs_for_runs(conn, [workflow_run_id])
        verifications = _verifications_for_runs(conn, [workflow_run_id])
        escalations = _escalations_for_runs(conn, [workflow_run_id])
        decisions = _decisions_for_escalations(conn, [str(escalation["id"]) for escalation in escalations])
        escalations = enrich_escalations_with_links(escalations, decisions)
        test_cases = _test_cases_for_runs(conn, [workflow_run_id])
        user_stories = _stories_for_test_cases(conn, test_cases)
        features = _features_for_test_cases(conn, test_cases)
        entities = [
            ("workflow_run", workflow_run_id),
            *[("agent_job", job["id"]) for job in jobs],
            *[("verification", verification["id"]) for verification in verifications],
            *[("escalation", escalation["id"]) for escalation in escalations],
            *[("decision", decision["id"]) for decision in decisions],
            *[("feature", feature["id"]) for feature in features],
            *[("user_story", story["id"]) for story in user_stories],
            *[("test_case", test_case["id"]) for test_case in test_cases],
        ]
        events = _events_for_entities(conn, entities)
        evidence = _evidence_for_report(conn, events=events, jobs=jobs)
        data = {
            "kind": "run",
            "id": workflow_run_id,
            "workflow_run": run,
            "agent_jobs": jobs,
            "verifications": verifications,
            "escalations": escalations,
            "decisions": decisions,
            "features": features,
            "user_stories": user_stories,
            "test_cases": test_cases,
            "evidence": evidence,
            "events": events,
        }
    finally:
        conn.close()
    path = _report_path(paths, "run", workflow_run_id)
    markdown = _render_run_report(data)
    _write_report(path, markdown)
    return {"ok": True, "kind": "run", "id": workflow_run_id, "path": str(path), "report": data}


def report_feature(paths: ProjectPaths, feature_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(feature_id, "feature_id")
    conn = connect(paths.db_path)
    try:
        feature = _one(conn, "SELECT * FROM features WHERE id = ?", (feature_id,))
        if feature is None:
            raise InvalidInputError(f"Feature does not exist: {feature_id}", details={"feature_id": feature_id})
        user_stories = _stories_for_feature(conn, feature_id)
        test_cases = _test_cases_for_feature(conn, feature_id)
        defects = _defects_for_feature(conn, feature_id)
        run_ids = _workflow_run_ids_for_feature(conn, test_cases=test_cases, defects=defects)
        runs = _rows_for_ids(conn, "workflow_runs", run_ids, "started_at, id")
        jobs = _jobs_for_runs(conn, run_ids)
        verifications = _verifications_for_runs(conn, run_ids)
        escalations = _escalations_for_runs(conn, run_ids)
        decisions = _decisions_for_escalations(conn, [str(escalation["id"]) for escalation in escalations])
        escalations = enrich_escalations_with_links(escalations, decisions)
        entities = [
            ("feature", feature_id),
            *[("user_story", story["id"]) for story in user_stories],
            *[("test_case", test_case["id"]) for test_case in test_cases],
            *[("defect", defect["id"]) for defect in defects],
            *[("workflow_run", run_id) for run_id in run_ids],
            *[("agent_job", job["id"]) for job in jobs],
            *[("verification", verification["id"]) for verification in verifications],
            *[("escalation", escalation["id"]) for escalation in escalations],
            *[("decision", decision["id"]) for decision in decisions],
        ]
        events = _events_for_entities(conn, entities)
        evidence = _evidence_for_report(conn, events=events, jobs=jobs)
        data = {
            "kind": "feature",
            "id": feature_id,
            "feature": feature,
            "user_stories": user_stories,
            "test_cases": test_cases,
            "defects": defects,
            "workflow_runs": runs,
            "agent_jobs": jobs,
            "verifications": verifications,
            "escalations": escalations,
            "decisions": decisions,
            "evidence": evidence,
            "events": events,
        }
    finally:
        conn.close()
    path = _report_path(paths, "feature", feature_id)
    markdown = _render_feature_report(data)
    _write_report(path, markdown)
    return {"ok": True, "kind": "feature", "id": feature_id, "path": str(path), "report": data}


def report_defect(paths: ProjectPaths, defect_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(defect_id, "defect_id")
    conn = connect(paths.db_path)
    try:
        defect = _one(conn, "SELECT * FROM defects WHERE id = ?", (defect_id,))
        if defect is None:
            raise InvalidInputError(f"Defect does not exist: {defect_id}", details={"defect_id": defect_id})
        feature = _one(conn, "SELECT * FROM features WHERE id = ?", (defect["feature_id"],))
        run_ids = _workflow_runs_for_defect(conn, defect_id)
        runs = _rows_for_ids(conn, "workflow_runs", run_ids, "started_at, id")
        jobs = _jobs_for_runs(conn, run_ids)
        verifications = _verifications_for_runs(conn, run_ids)
        escalations = _escalations_for_runs(conn, run_ids)
        decisions = _decisions_for_escalations(conn, [str(escalation["id"]) for escalation in escalations])
        escalations = enrich_escalations_with_links(escalations, decisions)
        entities = [
            ("defect", defect_id),
            ("feature", str(defect["feature_id"])),
            *[("workflow_run", run_id) for run_id in run_ids],
            *[("agent_job", job["id"]) for job in jobs],
            *[("verification", verification["id"]) for verification in verifications],
            *[("escalation", escalation["id"]) for escalation in escalations],
            *[("decision", decision["id"]) for decision in decisions],
        ]
        events = _events_for_entities(conn, entities)
        evidence = _evidence_for_report(conn, defect_id=defect_id, events=events, jobs=jobs)
        data = {
            "kind": "defect",
            "id": defect_id,
            "defect": defect,
            "feature": feature,
            "workflow_runs": runs,
            "agent_jobs": jobs,
            "verifications": verifications,
            "escalations": escalations,
            "decisions": decisions,
            "evidence": evidence,
            "events": events,
        }
    finally:
        conn.close()
    path = _report_path(paths, "defect", defect_id)
    markdown = _render_defect_report(data)
    _write_report(path, markdown)
    return {"ok": True, "kind": "defect", "id": defect_id, "path": str(path), "report": data}


def report_validation(paths: ProjectPaths, *, strict: bool = False) -> dict[str, Any]:
    require_initialized(paths)
    result = validate_project(paths, strict=strict)
    data = {
        "kind": "validation",
        "id": "strict" if strict else "current",
        "strict": strict,
        "ok": result.ok,
        "errors": result.errors,
        "warnings": result.warnings,
        "next_actions": _validation_next_actions(strict=strict, ok=result.ok),
    }
    path = paths.reports_dir / ("validation-strict.md" if strict else "validation.md")
    markdown = _render_validation_report(data)
    _write_report(path, markdown)
    return {"ok": True, "kind": "validation", "id": data["id"], "path": str(path), "report": data}


def _render_goal_report(data: dict[str, Any]) -> str:
    goal = data["goal"]
    parts = [
        f"# Goal Report: {goal['id']}",
        "",
        "## Summary",
        _kv_table(goal, ["id", "title", "status", "created_at", "updated_at"]),
        "",
        "## Completion",
        _json_block(goal.get("completion_json")),
        "",
        *_goal_tasks_section(data["tasks"]),
        "## Workflow Runs",
        _table(data["workflow_runs"], ["id", "workflow_id", "status", "iteration", "started_at", "ended_at", "summary"]),
        "",
        "## Agent Jobs",
        _table(data["agent_jobs"], ["id", "workflow_run_id", "role", "status", "prompt_path", "output_path", "summary"]),
        "",
        "## Verifications",
        _table(data["verifications"], ["id", "workflow_run_id", "target_job_id", "verifier_role", "result", "reasons_json", "created_at"]),
        "",
        "## Escalations",
        _table(data["escalations"], ["id", "workflow_run_id", "severity", "question", "recommendation", "linked_decision_ids", "status", "created_at"]),
        "",
        "## Decisions",
        _table(data["decisions"], ["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "blocks_json", "created_at"]),
        "",
        "## Features",
        _table(data["features"], ["id", "name", "surface", "status", "confidence", "updated_at"]),
        "",
        "## User Stories",
        _table(data["user_stories"], ["id", "feature_id", "actor", "goal", "status", "expected_behavior", "updated_at"]),
        "",
        "## Test Cases",
        _table(data["test_cases"], ["id", "feature_id", "story_id", "type", "scenario", "expected", "status", "last_run_id", "evidence_id", "updated_at"]),
        "",
        "## Evidence",
        _table(data["evidence"], ["id", "type", "path", "command", "summary", "created_at"]),
        "",
        "## Events",
        _table(data["events"], ["id", "event_type", "entity_type", "entity_id", "created_at", "payload_json"]),
        "",
    ]
    return "\n".join(parts)


def _render_run_report(data: dict[str, Any]) -> str:
    run = data["workflow_run"]
    parts = [
        f"# Workflow Run Report: {run['id']}",
        "",
        "## Summary",
        _kv_table(run, ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "ended_at", "summary"]),
        "",
        "## Agent Jobs",
        _table(data["agent_jobs"], ["id", "workflow_run_id", "role", "status", "prompt_path", "output_path", "summary"]),
        "",
        "## Verifications",
        _table(data["verifications"], ["id", "workflow_run_id", "target_job_id", "verifier_role", "result", "reasons_json", "created_at"]),
        "",
        *_verification_rubric_section(data["verifications"]),
        "## Escalations",
        _table(data["escalations"], ["id", "workflow_run_id", "severity", "question", "recommendation", "linked_decision_ids", "status", "created_at"]),
        "",
        "## Decisions",
        _table(data["decisions"], ["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "blocks_json", "created_at"]),
        "",
        "## Features",
        _table(data["features"], ["id", "name", "surface", "status", "confidence", "updated_at"]),
        "",
        "## User Stories",
        _table(data["user_stories"], ["id", "feature_id", "actor", "goal", "status", "expected_behavior", "updated_at"]),
        "",
        "## Test Cases",
        _table(data["test_cases"], ["id", "feature_id", "story_id", "type", "scenario", "expected", "status", "last_run_id", "evidence_id", "updated_at"]),
        "",
        "## Evidence",
        _table(data["evidence"], ["id", "type", "path", "command", "summary", "created_at"]),
        "",
        "## Events",
        _table(data["events"], ["id", "event_type", "entity_type", "entity_id", "created_at", "payload_json"]),
        "",
    ]
    return "\n".join(parts)


def _render_feature_report(data: dict[str, Any]) -> str:
    feature = data["feature"]
    parts = [
        f"# Feature Report: {feature['id']}",
        "",
        "## Summary",
        _kv_table(feature, ["id", "name", "surface", "description", "status", "confidence", "created_at", "updated_at"]),
        "",
        "## User Stories",
        _table(data["user_stories"], ["id", "feature_id", "actor", "goal", "status", "expected_behavior", "updated_at"]),
        "",
        "## Test Cases",
        _table(data["test_cases"], ["id", "feature_id", "story_id", "type", "scenario", "expected", "status", "last_run_id", "evidence_id", "updated_at"]),
        "",
        "## Defects",
        _table(data["defects"], ["id", "feature_id", "test_case_id", "severity", "status", "expected", "actual", "evidence_id", "updated_at"]),
        "",
        "## Workflow Runs",
        _table(data["workflow_runs"], ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "ended_at", "summary"]),
        "",
        "## Agent Jobs",
        _table(data["agent_jobs"], ["id", "workflow_run_id", "role", "status", "prompt_path", "output_path", "summary"]),
        "",
        "## Verifications",
        _table(data["verifications"], ["id", "workflow_run_id", "target_job_id", "verifier_role", "result", "reasons_json", "created_at"]),
        "",
        "## Escalations",
        _table(data["escalations"], ["id", "workflow_run_id", "severity", "question", "recommendation", "linked_decision_ids", "status", "created_at"]),
        "",
        "## Decisions",
        _table(data["decisions"], ["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "blocks_json", "created_at"]),
        "",
        "## Evidence",
        _table(data["evidence"], ["id", "type", "path", "command", "summary", "created_at"]),
        "",
        "## Events",
        _table(data["events"], ["id", "event_type", "entity_type", "entity_id", "created_at", "payload_json"]),
        "",
    ]
    return "\n".join(parts)


def _render_defect_report(data: dict[str, Any]) -> str:
    defect = data["defect"]
    parts = [
        f"# Defect Report: {defect['id']}",
        "",
        "## Summary",
        _kv_table(defect, ["id", "feature_id", "test_case_id", "severity", "status", "expected", "actual", "reproduction", "evidence_id", "created_at", "updated_at"]),
        "",
        "## Feature",
        _kv_table(data["feature"], ["id", "name", "surface", "status", "confidence", "updated_at"]) if data["feature"] else "No related feature found.",
        "",
        "## Workflow Runs",
        _table(data["workflow_runs"], ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "ended_at", "summary"]),
        "",
        "## Agent Jobs",
        _table(data["agent_jobs"], ["id", "workflow_run_id", "role", "status", "prompt_path", "output_path", "summary"]),
        "",
        "## Verifications",
        _table(data["verifications"], ["id", "workflow_run_id", "target_job_id", "verifier_role", "result", "reasons_json", "created_at"]),
        "",
        "## Escalations",
        _table(data["escalations"], ["id", "workflow_run_id", "severity", "question", "recommendation", "linked_decision_ids", "status", "created_at"]),
        "",
        "## Decisions",
        _table(data["decisions"], ["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "blocks_json", "created_at"]),
        "",
        "## Evidence",
        _table(data["evidence"], ["id", "type", "path", "command", "summary", "created_at"]),
        "",
        "## Events",
        _table(data["events"], ["id", "event_type", "entity_type", "entity_id", "created_at", "payload_json"]),
        "",
    ]
    return "\n".join(parts)


def _render_validation_report(data: dict[str, Any]) -> str:
    summary = {
        "strict": data["strict"],
        "ok": data["ok"],
        "error_count": len(data["errors"]),
        "warning_count": len(data["warnings"]),
    }
    error_rows = [{"message": message} for message in data["errors"]]
    warning_rows = [{"message": message} for message in data["warnings"]]
    parts = [
        "# Validation Report",
        "",
        "## Summary",
        _kv_table(summary, ["strict", "ok", "error_count", "warning_count"]),
        "",
        "## Errors",
        _table(error_rows, ["message"]),
        "",
        "## Warnings",
        _table(warning_rows, ["message"]),
        "",
        "## Suggested Next Actions",
        _table(data["next_actions"], ["priority", "command", "reason"]),
        "",
    ]
    return "\n".join(parts)


def _verification_rubric_section(verifications: list[dict[str, Any]]) -> list[str]:
    rows = _verification_rubric_rows(verifications)
    if not rows:
        return []
    return [
        "## Verification Rubrics",
        _table(
            rows,
            [
                "id",
                "criteria_yes",
                "criteria_no",
                "criteria_unknown",
                "criteria_total",
                "regression_risk",
                "confidence_score",
                "evidence_completeness",
            ],
        ),
        "",
    ]


def _verification_rubric_rows(verifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for verification in verifications:
        rubric = _json_object_from_value(verification.get("rubric_json"))
        if not claims_rubric_v1(rubric):
            continue
        criteria = rubric.get("acceptance_criteria") if isinstance(rubric, dict) else []
        criteria_items = [item for item in criteria if isinstance(item, dict)] if isinstance(criteria, list) else []
        counts = {
            "yes": sum(1 for item in criteria_items if item.get("met") == "yes"),
            "no": sum(1 for item in criteria_items if item.get("met") == "no"),
            "unknown": sum(1 for item in criteria_items if item.get("met") == "unknown"),
        }
        regression_risk = rubric.get("regression_risk") if isinstance(rubric.get("regression_risk"), dict) else {}
        rows.append(
            {
                "id": verification["id"],
                "criteria_yes": counts["yes"],
                "criteria_no": counts["no"],
                "criteria_unknown": counts["unknown"],
                "criteria_total": len(criteria_items),
                "regression_risk": regression_risk.get("level", ""),
                "confidence_score": rubric.get("confidence_score"),
                "evidence_completeness": rubric.get("evidence_completeness", ""),
            }
        )
    return rows


def _goal_tasks_section(tasks: list[dict[str, Any]]) -> list[str]:
    if not tasks:
        return []
    return [
        "## Tasks",
        _table(tasks, ["id", "title", "status", "priority", "unmet_dependency_count"]),
        "",
    ]


def _report_path(paths: ProjectPaths, kind: str, entity_id: str) -> Path:
    return paths.reports_dir / f"{kind}-{entity_id}.md"


def _write_report(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _one(conn, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def _rows(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _rows_for_ids(conn, table: str, ids: list[str], order_by: str) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    return _rows(conn, f"SELECT * FROM {table} WHERE id IN ({placeholders}) ORDER BY {order_by}", tuple(ids))


def _jobs_for_runs(conn, run_ids: list[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ", ".join("?" for _ in run_ids)
    return _rows(
        conn,
        f"SELECT * FROM agent_jobs WHERE workflow_run_id IN ({placeholders}) ORDER BY workflow_run_id, id",
        tuple(run_ids),
    )


def _verifications_for_runs(conn, run_ids: list[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ", ".join("?" for _ in run_ids)
    return _rows(
        conn,
        f"SELECT * FROM verifications WHERE workflow_run_id IN ({placeholders}) ORDER BY created_at, id",
        tuple(run_ids),
    )


def _escalations_for_runs(conn, run_ids: list[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ", ".join("?" for _ in run_ids)
    return _rows(
        conn,
        f"SELECT * FROM escalations WHERE workflow_run_id IN ({placeholders}) ORDER BY created_at, id",
        tuple(run_ids),
    )


def _decisions_for_escalations(conn, escalation_ids: list[str]) -> list[dict[str, Any]]:
    if not escalation_ids:
        return []
    decisions = enrich_decisions_with_links(
        _rows(conn, "SELECT * FROM decisions ORDER BY created_at, id")
    )
    escalation_id_set = set(escalation_ids)
    return [
        decision
        for decision in decisions
        if escalation_id_set.intersection(decision.get("linked_escalation_ids", []))
    ]


def _tasks_for_goal(conn, goal_id: str) -> list[dict[str, Any]]:
    status_order_sql = _task_status_order_sql("tasks.status")
    completed_placeholders = ", ".join("?" for _ in TASK_COMPLETED_DEPENDENCY_STATUSES)
    rows = _rows(
        conn,
        f"""
        SELECT
          tasks.id,
          tasks.title,
          tasks.status,
          tasks.priority,
          SUM(
            CASE
              WHEN task_dependencies.depends_on_task_id IS NOT NULL
               AND dependency.status NOT IN ({completed_placeholders})
              THEN 1
              ELSE 0
            END
          ) AS unmet_dependency_count
        FROM tasks
        LEFT JOIN task_dependencies
          ON task_dependencies.task_id = tasks.id
        LEFT JOIN tasks AS dependency
          ON dependency.id = task_dependencies.depends_on_task_id
        WHERE tasks.related_goal_id = ?
        GROUP BY tasks.id
        ORDER BY {status_order_sql}, tasks.priority, tasks.id
        """,
        tuple(sorted(TASK_COMPLETED_DEPENDENCY_STATUSES)) + (goal_id,),
    )
    for row in rows:
        row["unmet_dependency_count"] = int(row["unmet_dependency_count"] or 0)
    return rows


def _task_status_order_sql(column: str) -> str:
    cases = " ".join(
        f"WHEN '{status}' THEN {index}" for status, index in TASK_STATUS_ORDER.items()
    )
    return f"CASE {column} {cases} ELSE 99 END"


def _stories_for_feature(conn, feature_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT *
        FROM user_stories
        WHERE feature_id = ?
        ORDER BY created_at, id
        """,
        (feature_id,),
    )


def _test_cases_for_feature(conn, feature_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT *
        FROM test_cases
        WHERE feature_id = ?
        ORDER BY created_at, id
        """,
        (feature_id,),
    )


def _defects_for_feature(conn, feature_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT *
        FROM defects
        WHERE feature_id = ?
        ORDER BY created_at, id
        """,
        (feature_id,),
    )


def _workflow_run_ids_for_feature(
    conn,
    *,
    test_cases: list[dict[str, Any]],
    defects: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    test_case_ids = {str(test_case["id"]) for test_case in test_cases}
    defect_ids = {str(defect["id"]) for defect in defects}
    ids.extend(str(test_case["last_run_id"]) for test_case in test_cases if test_case.get("last_run_id"))
    for defect_id in defect_ids:
        ids.extend(_workflow_runs_for_defect(conn, defect_id))

    event_rows = _rows(
        conn,
        """
        SELECT entity_id, entity_type, payload_json
        FROM events
        WHERE entity_type IN ('test_case', 'workflow_run')
        ORDER BY rowid
        """,
    )
    for event in event_rows:
        payload = _payload(event)
        if event["entity_type"] == "test_case" and event.get("entity_id") in test_case_ids:
            workflow_run_id = payload.get("workflow_run_id")
            if isinstance(workflow_run_id, str) and workflow_run_id:
                ids.append(workflow_run_id)
        if event["entity_type"] == "workflow_run" and payload.get("defect_id") in defect_ids and event.get("entity_id"):
            ids.append(str(event["entity_id"]))
    return sorted(set(ids), key=ids.index)


def _test_cases_for_runs(conn, run_ids: list[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    run_id_set = set(run_ids)
    test_case_ids: list[str] = []

    placeholders = ", ".join("?" for _ in run_ids)
    rows = _rows(
        conn,
        f"SELECT id FROM test_cases WHERE last_run_id IN ({placeholders}) ORDER BY id",
        tuple(run_ids),
    )
    test_case_ids.extend(str(row["id"]) for row in rows)

    event_rows = _rows(
        conn,
        """
        SELECT entity_id, payload_json
        FROM events
        WHERE entity_type = 'test_case'
        ORDER BY rowid
        """,
    )
    for event in event_rows:
        payload = _payload(event)
        if payload.get("workflow_run_id") in run_id_set and event.get("entity_id"):
            test_case_ids.append(str(event["entity_id"]))

    unique_ids = sorted(set(test_case_ids))
    return _rows_for_ids(conn, "test_cases", unique_ids, "id")


def _stories_for_test_cases(conn, test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    story_ids = sorted({str(test_case["story_id"]) for test_case in test_cases if test_case.get("story_id")})
    return _rows_for_ids(conn, "user_stories", story_ids, "id")


def _features_for_test_cases(conn, test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feature_ids = sorted({str(test_case["feature_id"]) for test_case in test_cases if test_case.get("feature_id")})
    return _rows_for_ids(conn, "features", feature_ids, "id")


def _workflow_runs_for_defect(conn, defect_id: str) -> list[str]:
    ids: list[str] = []
    rows = _rows(
        conn,
        """
        SELECT entity_id, payload_json FROM events
        WHERE entity_type = 'workflow_run' AND event_type = 'workflow_run_created'
        ORDER BY rowid
        """,
    )
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            continue
        if payload.get("defect_id") == defect_id and row["entity_id"]:
            ids.append(str(row["entity_id"]))
    return sorted(set(ids), key=ids.index)


def _evidence_for_report(
    conn,
    *,
    defect_id: str | None = None,
    events: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids: list[str] = []
    if defect_id:
        defect = _one(conn, "SELECT evidence_id FROM defects WHERE id = ?", (defect_id,))
        if defect and defect.get("evidence_id"):
            ids.append(str(defect["evidence_id"]))
    for event in events:
        payload = _payload(event)
        for key in ("evidence_id",):
            value = payload.get(key)
            if isinstance(value, str) and value:
                ids.append(value)
    output_paths = sorted({str(job["output_path"]) for job in jobs if job.get("output_path")})
    if output_paths:
        placeholders = ", ".join("?" for _ in output_paths)
        rows = _rows(
            conn,
            f"SELECT id FROM evidence WHERE path IN ({placeholders}) ORDER BY created_at, id",
            tuple(output_paths),
        )
        ids.extend(str(row["id"]) for row in rows)
    unique_ids = sorted(set(ids))
    if not unique_ids:
        return []
    placeholders = ", ".join("?" for _ in unique_ids)
    return _rows(conn, f"SELECT * FROM evidence WHERE id IN ({placeholders}) ORDER BY created_at, id", tuple(unique_ids))


def _events_for_entities(conn, entities: list[tuple[str, str]]) -> list[dict[str, Any]]:
    if not entities:
        return []
    clauses = []
    params: list[str] = []
    for entity_type, entity_id in entities:
        clauses.append("(entity_type = ? AND entity_id = ?)")
        params.extend([entity_type, entity_id])
    sql = f"SELECT * FROM events WHERE {' OR '.join(clauses)} ORDER BY rowid"
    return _rows(conn, sql, tuple(params))


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return _json_object_from_value(event.get("payload_json"))


def _json_object_from_value(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _validation_next_actions(*, strict: bool, ok: bool) -> list[dict[str, Any]]:
    if ok:
        return [
            {
                "priority": 1,
                "command": "pcl next --strict" if strict else "pcl next",
                "reason": "Validation passed; continue the project loop.",
            }
        ]
    validate_command = "pcl validate --strict --json" if strict else "pcl validate --json"
    report_command = "pcl report validation --strict" if strict else "pcl report validation"
    return [
        {
            "priority": 1,
            "command": validate_command,
            "reason": "Review machine-readable validation diagnostics.",
        },
        {
            "priority": 2,
            "command": report_command,
            "reason": "Regenerate this human-review report after any investigation.",
        },
        {
            "priority": 3,
            "command": "manual review",
            "reason": "State or audit-log repair requires human approval before mutation.",
        },
    ]


def _kv_table(row: dict[str, Any], fields: list[str]) -> str:
    lines = ["| Field | Value |", "|---|---|"]
    for field in fields:
        lines.append(f"| {_md(field)} | {_md(_format_value(row.get(field)))} |")
    return "\n".join(lines)


def _table(rows: list[dict[str, Any]], fields: list[str]) -> str:
    if not rows:
        return "No records."
    lines = ["| " + " | ".join(_md(field) for field in fields) + " |"]
    lines.append("|" + "|".join("---" for _ in fields) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_md(_format_value(row.get(field))) for field in fields) + " |")
    return "\n".join(lines)


def _json_block(raw: Any) -> str:
    if raw is None or raw == "":
        return "```json\n{}\n```"
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        parsed = raw
    return "```json\n" + json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n```"


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )
