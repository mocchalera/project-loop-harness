from __future__ import annotations

import html
import json
from typing import Any

from .commands import decision_options, escalation_options, generic_human_options, next_action, verification_options
from .db import connect, count_rows
from .guards import require_initialized
from .evidence import EXECUTION_PROVENANCE_EVIDENCE_TYPE, provenance_presentation
from .links import enrich_decisions_with_links, enrich_escalations_with_links
from .lifecycle import ACTIVE_RUN_STATUSES
from .locales import dashboard_strings, resolve_dashboard_locale
from .paths import ProjectPaths
from .resources import read_text_resource
from .validators import validate_project
from .workflow_proposals import list_workflow_proposals
from .workflows import enrich_jobs_with_evidence
from .workflow_yaml import parse_workflow_yaml


DASHBOARD_DATA_CONTRACT_VERSION = "dashboard-data/v1"
ENTITY_ID_PREFIXES = ("D-", "DEC-", "E-", "ESC-", "F-", "G-", "J-", "T-", "TC-", "US-", "V-", "WR-")
SEVERITY_RANKS = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
HUMAN_DECISION_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TASK_STATUS_ORDER = {
    "in_progress": 0,
    "ready": 1,
    "todo": 2,
    "blocked": 3,
    "done": 4,
    "waived": 5,
    "cancelled": 6,
}


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _state_timestamp(conn) -> str:
    row = conn.execute("SELECT MAX(created_at) AS generated_at FROM events").fetchone()
    return str(row["generated_at"] or "")


def _one(conn, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def _goal_rows(conn) -> list[dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT id, title, status, completion_json, updated_at
        FROM goals
        ORDER BY created_at DESC, id DESC
        LIMIT 20
        """,
    )
    for row in rows:
        try:
            completion = json.loads(str(row.get("completion_json") or "{}"))
        except json.JSONDecodeError:
            completion = {}
        closure = completion.get("closure", {}) if isinstance(completion, dict) else {}
        if not isinstance(closure, dict):
            closure = {}
        row["closure_proof"] = {
            "proof_type": closure.get("proof_type"),
            "evidence_id": closure.get("evidence_id"),
            "verification_id": closure.get("verification_id"),
            "packet_outcome": closure.get("packet_outcome"),
        }
        row.pop("completion_json", None)
    return rows


def render_dashboard(paths: ProjectPaths, *, locale: str | None = None) -> None:
    require_initialized(paths)
    resolved_locale = resolve_dashboard_locale(paths, locale)
    validation = validate_project(paths)

    conn = connect(paths.db_path)
    try:
        current_goal = _one(
            conn,
            """
            SELECT id, title, status, completion_json, budget_json, updated_at
            FROM goals
            WHERE status NOT IN ('closed', 'cancelled')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
        )
        active_workflow = _one(
            conn,
            """
            SELECT id, workflow_id, goal_id, status, iteration, started_at, summary
            FROM workflow_runs
            WHERE status IN ('queued', 'running', 'blocked')
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
        )
        active_run_id = active_workflow["id"] if active_workflow else None
        risk_rows = _risk_source_rows(conn)
        action = next_action(paths)
        all_decision_link_rows = _rows(
            conn,
            """
            SELECT id, blocks_json
            FROM decisions
            ORDER BY id
            """,
        )
        open_decisions = enrich_decisions_with_links(risk_rows["decisions"])
        open_escalations = enrich_escalations_with_links(
            risk_rows["escalations"],
            all_decision_link_rows,
        )
        data = {
            "contract_version": DASHBOARD_DATA_CONTRACT_VERSION,
            "generated_at": _state_timestamp(conn),
            "source_db": str(paths.db_path),
            "validation": validation.to_dict(),
            "next_action": action,
            "counts": {
                "features": count_rows(conn, "features"),
                "user_stories": count_rows(conn, "user_stories"),
                "test_cases": count_rows(conn, "test_cases"),
                "open_defects": count_rows(conn, "defects", "status NOT IN (?, ?)", ("closed", "waived")),
                "goals": count_rows(conn, "goals"),
                "open_decisions": count_rows(conn, "decisions", "status = ?", ("open",)),
                "workflow_runs": count_rows(conn, "workflow_runs"),
                "queued_jobs": count_rows(conn, "agent_jobs", "status = ?", ("queued",)),
                "open_escalations": count_rows(conn, "escalations", "status = ?", ("open",)),
                "workflow_proposals": len(list(paths.workflow_proposals_dir.glob("WP-*.yaml")))
                if paths.workflow_proposals_dir.exists()
                else 0,
            },
            "current_goal": current_goal,
            "active_workflow": _with_workflow_budget(paths, active_workflow),
            "active_agent_jobs": _rows(
                conn,
                """
                SELECT id, workflow_run_id, role, status, assigned_agent_id, attempts,
                       lease_expires_at, last_heartbeat_at, prompt_path, output_path, summary
                FROM agent_jobs
                WHERE workflow_run_id = ?
                ORDER BY id
                LIMIT 20
                """,
                (active_run_id or "",),
            )
            if active_run_id
            else [],
            "features": _rows(
                conn,
                """
                SELECT id, name, surface, status, confidence, updated_at
                FROM features
                ORDER BY id
                LIMIT 50
                """,
            ),
            "user_stories": _rows(
                conn,
                """
                SELECT id, feature_id, actor, goal, benefit, expected_behavior, status, updated_at
                FROM user_stories
                ORDER BY created_at DESC, id DESC
                LIMIT 50
                """,
            ),
            "test_cases": _rows(
                conn,
                """
                SELECT id, feature_id, story_id, type, scenario, expected, status, last_run_id, evidence_id, updated_at
                FROM test_cases
                ORDER BY created_at DESC, id DESC
                LIMIT 50
                """,
            ),
            "defects": _rows(
                conn,
                """
                SELECT id, feature_id, severity, status, expected, actual, updated_at
                FROM defects
                ORDER BY created_at DESC
                LIMIT 50
                """,
            ),
            "tasks": _task_rows(conn),
            "goals": _goal_rows(conn),
            "workflow_runs": _rows(
                conn,
                """
                SELECT id, workflow_id, goal_id, status, iteration, started_at, summary
                FROM workflow_runs
                ORDER BY started_at DESC, id DESC
                LIMIT 20
                """,
            ),
            "agent_jobs": _rows(
                conn,
                """
                SELECT id, workflow_run_id, role, status, assigned_agent_id, attempts,
                       lease_expires_at, last_heartbeat_at, prompt_path, output_path, summary
                FROM agent_jobs
                ORDER BY id
                LIMIT 50
                """,
            ),
            "verifications": _rows(
                conn,
                """
                SELECT id, workflow_run_id, target_job_id, verifier_role, result, reasons_json, created_at
                FROM verifications
                ORDER BY created_at DESC, id DESC
                LIMIT 20
                """,
            ),
            "decisions": _rows(
                conn,
                """
                SELECT id, status, question, recommendation, selected_option, reason, blocks_json, created_at
                FROM decisions
                ORDER BY created_at DESC, id DESC
                LIMIT 20
                """,
            ),
            "escalations": _rows(
                conn,
                """
                SELECT id, workflow_run_id, severity, question, recommendation, status, created_at
                FROM escalations
                ORDER BY created_at DESC, id DESC
                LIMIT 20
                """,
            ),
            "evidence": _rows(
                conn,
                """
                SELECT id, type, path, command, summary, created_at
                FROM evidence
                ORDER BY created_at DESC, id DESC
                LIMIT 20
                """,
            ),
            "recent_events": _rows(
                conn,
                """
                SELECT id, event_type, entity_type, entity_id, created_at
                FROM events
                ORDER BY rowid DESC
                LIMIT 20
                """,
            ),
            "reports": _report_rows(paths),
            "workflow_proposals": list_workflow_proposals(paths, validate=False),
        }
        enrich_jobs_with_evidence(conn, data["active_agent_jobs"])
        enrich_jobs_with_evidence(conn, data["agent_jobs"])
        data["decisions"] = enrich_decisions_with_links(data["decisions"])
        data["escalations"] = enrich_escalations_with_links(data["escalations"], data["decisions"])
        for evidence in data["evidence"]:
            if evidence["type"] == EXECUTION_PROVENANCE_EVIDENCE_TYPE:
                evidence["provenance"] = provenance_presentation(paths, evidence_id=str(evidence["id"]))
                skills = evidence["provenance"]["skills"]
                evidence["skill_names"] = ", ".join(str(item["name"]) for item in skills)
                evidence["skill_recorded_hashes"] = ", ".join(str(item["recorded_sha256"]) for item in skills)
                evidence["skill_health"] = ", ".join(str(item["health"]) for item in skills)
        _enrich_navigation(paths, data)
        data["risk_summary"] = _risk_summary(data, risk_rows)
        data["human_decisions"] = _human_decisions(
            conn,
            paths=paths,
            action=action,
            open_decisions=open_decisions,
            open_escalations=open_escalations,
        )
    finally:
        conn.close()

    paths.dashboard_dir.mkdir(parents=True, exist_ok=True)
    paths.dashboard_data.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.dashboard_html.write_text(_render_html(data, locale=resolved_locale), encoding="utf-8")


def _with_workflow_budget(paths: ProjectPaths, active_workflow: dict[str, Any] | None) -> dict[str, Any] | None:
    if active_workflow is None:
        return None
    budget = {}
    workflow_id = str(active_workflow["workflow_id"])
    workflow_path = paths.workflows_dir / f"{workflow_id}.yaml"
    if workflow_path.exists():
        try:
            parsed = parse_workflow_yaml(workflow_path.read_text(encoding="utf-8"))
            raw_budget = parsed.get("budget", {})
            if isinstance(raw_budget, dict):
                budget = raw_budget
        except Exception as exc:
            budget = {"parse_error": str(exc)}
    enriched = dict(active_workflow)
    enriched["budget"] = budget
    return enriched


def _report_rows(paths: ProjectPaths) -> list[dict[str, str]]:
    if not paths.reports_dir.exists():
        return []
    rows = []
    for path in sorted(paths.reports_dir.glob("*.md"), key=lambda item: item.name):
        rows.append(
            {
                "path": str(path.relative_to(paths.root)),
                "name": path.stem,
            }
        )
    return rows


def _task_rows(conn) -> list[dict[str, Any]]:
    status_order_sql = _task_status_order_sql("tasks.status")
    rows = _rows(
        conn,
        f"""
        SELECT
          id,
          title,
          status,
          priority,
          owner,
          risk,
          effort,
          related_goal_id,
          related_feature_id,
          related_defect_id,
          created_at,
          updated_at
        FROM tasks
        ORDER BY {status_order_sql}, priority, id
        """,
    )
    dependencies = _task_dependency_map(conn, source_column="task_id", related_column="depends_on_task_id")
    dependents = _task_dependency_map(conn, source_column="depends_on_task_id", related_column="task_id")
    for row in rows:
        task_id = str(row["id"])
        row["dependency_ids"] = dependencies.get(task_id, [])
        row["dependent_ids"] = dependents.get(task_id, [])
    return rows


def _task_status_order_sql(column: str) -> str:
    cases = " ".join(
        f"WHEN '{status}' THEN {index}" for status, index in TASK_STATUS_ORDER.items()
    )
    return f"CASE {column} {cases} ELSE 99 END"


def _task_dependency_map(conn, *, source_column: str, related_column: str) -> dict[str, list[str]]:
    rows = conn.execute(
        f"""
        SELECT {source_column} AS task_id, {related_column} AS related_task_id
        FROM task_dependencies
        ORDER BY {source_column}, {related_column}
        """
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(str(row["task_id"]), []).append(str(row["related_task_id"]))
    return result


def _enrich_navigation(paths: ProjectPaths, data: dict[str, Any]) -> None:
    jobs_by_id = _rows_by_id(data["agent_jobs"])
    evidence_by_id = _rows_by_id(data["evidence"])
    report_texts = _report_texts(paths, data["reports"])

    for evidence in data["evidence"]:
        evidence["related_agent_job_ids"] = []
        evidence["related_workflow_run_ids"] = []
        evidence["related_report_paths"] = []

    for job in data["agent_jobs"]:
        for evidence_id in job.get("evidence_ids", []):
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                continue
            _append_unique(evidence["related_agent_job_ids"], str(job["id"]))
            _append_unique(evidence["related_workflow_run_ids"], str(job["workflow_run_id"]))

    for report in data["reports"]:
        report["related_evidence_ids"] = []
        report["related_agent_job_ids"] = []
        report["related_workflow_run_ids"] = []
        text = report_texts.get(str(report["path"]), "")
        for evidence in data["evidence"]:
            evidence_id = str(evidence["id"])
            evidence_path = str(evidence["path"])
            if evidence_id in text or evidence_path in text:
                _append_unique(report["related_evidence_ids"], evidence_id)
                _append_unique(evidence["related_report_paths"], str(report["path"]))
        for job in data["agent_jobs"]:
            job_id = str(job["id"])
            if job_id in text:
                _append_unique(report["related_agent_job_ids"], job_id)
        for run in data["workflow_runs"]:
            run_id = str(run["id"])
            if report["name"] == f"run-{run_id}" or run_id in text:
                _append_unique(report["related_workflow_run_ids"], run_id)

    run_report_paths = {
        str(report["name"]).removeprefix("run-"): str(report["path"])
        for report in data["reports"]
        if str(report["name"]).startswith("run-")
    }
    for verification in data["verifications"]:
        target_job_id = verification.get("target_job_id")
        job = jobs_by_id.get(str(target_job_id)) if target_job_id else None
        verification["target_job_evidence_ids"] = list(job.get("evidence_ids", [])) if job else []
        verification["workflow_report_path"] = run_report_paths.get(str(verification["workflow_run_id"]))


def _rows_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in rows if row.get("id")}


def _report_texts(paths: ProjectPaths, reports: list[dict[str, str]]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for report in reports:
        report_path = paths.root / str(report["path"])
        if report_path.exists() and report_path.is_file():
            texts[str(report["path"])] = report_path.read_text(encoding="utf-8", errors="replace")
        else:
            texts[str(report["path"])] = ""
    return texts


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _risk_source_rows(conn) -> dict[str, list[dict[str, Any]]]:
    return {
        "decisions": _rows(
            conn,
            """
            SELECT id, status, question, recommendation, selected_option, reason, blocks_json, created_at
            FROM decisions
            WHERE status = 'open'
            ORDER BY created_at ASC, id ASC
            """,
        ),
        "escalations": _rows(
            conn,
            """
            SELECT id, workflow_run_id, severity, question, recommendation, status, created_at
            FROM escalations
            WHERE status = 'open'
            ORDER BY created_at ASC, id ASC
            """,
        ),
        "defects": _rows(
            conn,
            """
            SELECT id, feature_id, severity, status, expected, actual, updated_at
            FROM defects
            WHERE status NOT IN ('closed', 'waived')
            ORDER BY created_at ASC, id ASC
            """,
        ),
        "workflow_runs": _rows(
            conn,
            """
            SELECT id, workflow_id, goal_id, status, iteration, started_at, summary
            FROM workflow_runs
            WHERE status IN ('failed', 'blocked')
            ORDER BY started_at ASC, id ASC
            """,
        ),
        "agent_jobs": _rows(
            conn,
            """
            SELECT id, workflow_run_id, role, status, prompt_path, output_path, summary
            FROM agent_jobs
            WHERE status IN ('failed', 'blocked')
            ORDER BY id ASC
            """,
        ),
    }


def _human_decisions(
    conn,
    *,
    paths: ProjectPaths,
    action: dict[str, Any],
    open_decisions: list[dict[str, Any]],
    open_escalations: list[dict[str, Any]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    for decision in open_decisions:
        decision_id = str(decision.get("id", ""))
        items.append(
            _with_cockpit_fields(
                {
                    "kind": "decision",
                    "id": decision_id,
                    "question": str(decision.get("question", "")),
                    "recommendation": str(decision.get("recommendation", "")),
                    "created_at": str(decision.get("created_at", "")),
                    "resolve_command": (
                        f"pcl decision resolve {decision_id} --selected-option '<option>' "
                        "--reason '<why>'"
                    ),
                    "linked_escalation_ids": list(decision.get("linked_escalation_ids", [])),
                },
                why_blocked=f"Open decision {decision_id} blocks safe continuation until a human records an outcome.",
                options=decision_options(decision_id),
                recommendation=str(decision.get("recommendation", "")),
                recommendation_reason="This recommendation was recorded when the decision was opened.",
                related_evidence_paths=_decision_related_evidence_paths(conn, paths, decision),
            )
        )

    for escalation in open_escalations:
        escalation_id = str(escalation.get("id", ""))
        linked_decision_ids = list(escalation.get("linked_decision_ids", []))
        decision_id = linked_decision_ids[0] if linked_decision_ids else "DEC-xxxx"
        items.append(
            _with_cockpit_fields(
                {
                    "kind": "escalation",
                    "id": escalation_id,
                    "severity": str(escalation.get("severity", "")),
                    "question": str(escalation.get("question", "")),
                    "recommendation": str(escalation.get("recommendation", "")),
                    "created_at": str(escalation.get("created_at", "")),
                    "resolve_command": (
                        f"pcl escalation resolve {escalation_id} --decision {decision_id} "
                        "--summary '<summary>'"
                    ),
                    "linked_decision_ids": linked_decision_ids,
                },
                why_blocked=f"Open escalation {escalation_id} requires a human outcome before the loop can continue safely.",
                options=escalation_options(
                    escalation_id,
                    linked_decision_ids=[str(item) for item in linked_decision_ids],
                    workflow_run_id=str(escalation.get("workflow_run_id") or ""),
                ),
                recommendation=str(escalation.get("recommendation", "")),
                recommendation_reason="This recommendation was recorded when the escalation was opened.",
                related_evidence_paths=_escalation_related_evidence_paths(conn, paths, escalation),
            )
        )

    for verification in _active_needs_human_verifications(conn):
        verification_id = str(verification.get("id", ""))
        workflow_run_id = str(verification.get("workflow_run_id", ""))
        items.append(
            _with_cockpit_fields(
                {
                    "kind": "verification",
                    "id": verification_id,
                    "workflow_run_id": workflow_run_id,
                    "reasons": _json_string_list(verification.get("reasons_json")),
                    "created_at": str(verification.get("created_at", "")),
                    "resolve_command": (
                        f"pcl escalation open --run {workflow_run_id} --severity high "
                        "--question 'What human decision is needed?' "
                        "--recommendation 'Review the needs_human verification and choose the next step'"
                    ),
                },
                why_blocked=(
                    f"Verification {verification_id} is needs_human for workflow run {workflow_run_id}."
                ),
                options=verification_options(workflow_run_id),
                recommendation="Choose a verification outcome or open an escalation for missing evidence.",
                recommendation_reason="The verifier explicitly returned needs_human for this active workflow run.",
                related_evidence_paths=_verification_related_evidence_paths(conn, paths, verification),
            )
        )

    if action.get("requires_human") is True:
        items.append(
            _with_cockpit_fields(
                {
                    "kind": "next_action",
                    "type": str(action.get("type", "")),
                    "command": str(action.get("command", "")),
                    "reason": str(action.get("reason", "")),
                    "recommendation": str(action.get("recommendation", "")),
                    "recommendation_reason": str(action.get("recommendation_reason", "")),
                    "why_blocked": str(action.get("why_blocked", "")),
                },
                why_blocked=str(action.get("why_blocked") or action.get("reason") or ""),
                options=_action_options(action),
                recommendation=str(action.get("recommendation") or action.get("command") or ""),
                recommendation_reason=str(action.get("recommendation_reason") or action.get("reason") or ""),
                related_evidence_paths=_action_related_evidence_paths(conn, paths, action),
            )
        )

    ordered = sorted(items, key=_human_decision_sort_key)
    return {"count": len(ordered), "items": ordered}


def _with_cockpit_fields(
    item: dict[str, Any],
    *,
    why_blocked: str,
    options: list[dict[str, str]],
    recommendation: str,
    recommendation_reason: str,
    related_evidence_paths: list[str],
) -> dict[str, Any]:
    enriched = dict(item)
    enriched["why_blocked"] = why_blocked
    enriched["options"] = _normalize_options(options)
    enriched["recommendation"] = recommendation
    enriched["recommendation_reason"] = recommendation_reason
    enriched["related_evidence_paths"] = _unique_sorted_texts(related_evidence_paths)
    enriched["receipt_paths"] = []
    return enriched


def _normalize_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized = []
    for option in options:
        normalized.append(
            {
                "label": str(option.get("label", "")),
                "command": str(option.get("command", "")),
                "why_safe": str(option.get("why_safe", "")),
                "risk_if_run": str(option.get("risk_if_run", "")),
            }
        )
    return normalized


def _action_options(action: dict[str, Any]) -> list[dict[str, str]]:
    options = action.get("options")
    if isinstance(options, list):
        return _normalize_options([option for option in options if isinstance(option, dict)])
    return generic_human_options(str(action.get("command", "")))


def _decision_related_evidence_paths(conn, paths: ProjectPaths, decision: dict[str, Any]) -> list[str]:
    evidence_paths: list[str] = []
    for block in _json_object_list(decision.get("blocks_json")):
        block_type = str(block.get("type") or "")
        block_id = str(block.get("id") or "")
        if not block_type or not block_id:
            continue
        evidence_paths.extend(_related_paths_for_reference(conn, paths, block_type, block_id))
    for escalation_id in decision.get("linked_escalation_ids", []):
        evidence_paths.extend(_related_paths_for_reference(conn, paths, "escalation", str(escalation_id)))
    return _unique_sorted_texts(evidence_paths)


def _escalation_related_evidence_paths(conn, paths: ProjectPaths, escalation: dict[str, Any]) -> list[str]:
    workflow_run_id = str(escalation.get("workflow_run_id") or "")
    if not workflow_run_id:
        return []
    return _workflow_run_evidence_paths(conn, paths, workflow_run_id)


def _verification_related_evidence_paths(conn, paths: ProjectPaths, verification: dict[str, Any]) -> list[str]:
    evidence_paths = _workflow_run_evidence_paths(conn, paths, str(verification.get("workflow_run_id") or ""))
    target_job_id = str(verification.get("target_job_id") or "")
    if target_job_id:
        evidence_paths.extend(_agent_job_evidence_paths(conn, [target_job_id]))
    return _unique_sorted_texts(evidence_paths)


def _action_related_evidence_paths(conn, paths: ProjectPaths, action: dict[str, Any]) -> list[str]:
    target = action.get("target")
    if not isinstance(target, dict):
        return []
    evidence_paths: list[str] = []
    workflow_run_id = str(target.get("workflow_run_id") or "")
    target_id = str(target.get("id") or "")
    if not workflow_run_id and target_id.startswith("WR-"):
        workflow_run_id = target_id
    if workflow_run_id:
        evidence_paths.extend(_workflow_run_evidence_paths(conn, paths, workflow_run_id))
    verification_id = str(target.get("verification_id") or "")
    if verification_id:
        evidence_paths.extend(_related_paths_for_reference(conn, paths, "verification", verification_id))
    return _unique_sorted_texts(evidence_paths)


def _related_paths_for_reference(conn, paths: ProjectPaths, reference_type: str, reference_id: str) -> list[str]:
    if reference_type == "evidence":
        return _evidence_paths_by_ids(conn, [reference_id])
    if reference_type == "agent_job":
        return _agent_job_evidence_paths(conn, [reference_id])
    if reference_type == "workflow_run":
        return _workflow_run_evidence_paths(conn, paths, reference_id)
    if reference_type == "verification":
        row = conn.execute(
            """
            SELECT id, workflow_run_id, target_job_id, reasons_json
            FROM verifications
            WHERE id = ?
            """,
            (reference_id,),
        ).fetchone()
        return _verification_related_evidence_paths(conn, paths, dict(row)) if row else []
    if reference_type == "escalation":
        row = conn.execute(
            """
            SELECT id, workflow_run_id
            FROM escalations
            WHERE id = ?
            """,
            (reference_id,),
        ).fetchone()
        return _escalation_related_evidence_paths(conn, paths, dict(row)) if row else []
    if reference_type in {"path", "report"}:
        return [reference_id]
    return []


def _workflow_run_evidence_paths(conn, paths: ProjectPaths, workflow_run_id: str) -> list[str]:
    if not workflow_run_id:
        return []
    evidence_paths: list[str] = []
    report_path = paths.reports_dir / f"run-{workflow_run_id}.md"
    if report_path.exists():
        evidence_paths.append(str(report_path.relative_to(paths.root)))
    job_rows = conn.execute(
        """
        SELECT id, workflow_run_id, role, status, prompt_path, output_path, summary
        FROM agent_jobs
        WHERE workflow_run_id = ?
        ORDER BY id
        """,
        (workflow_run_id,),
    ).fetchall()
    jobs = [dict(row) for row in job_rows]
    enrich_jobs_with_evidence(conn, jobs)
    for job in jobs:
        evidence_paths.extend(str(evidence.get("path", "")) for evidence in job.get("evidence", []))
    return _unique_sorted_texts(evidence_paths)


def _agent_job_evidence_paths(conn, job_ids: list[str]) -> list[str]:
    if not job_ids:
        return []
    placeholders = ", ".join("?" for _ in job_ids)
    rows = conn.execute(
        f"""
        SELECT id, workflow_run_id, role, status, prompt_path, output_path, summary
        FROM agent_jobs
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        tuple(job_ids),
    ).fetchall()
    jobs = [dict(row) for row in rows]
    enrich_jobs_with_evidence(conn, jobs)
    evidence_paths: list[str] = []
    for job in jobs:
        evidence_paths.extend(str(evidence.get("path", "")) for evidence in job.get("evidence", []))
    return _unique_sorted_texts(evidence_paths)


def _evidence_paths_by_ids(conn, evidence_ids: list[str]) -> list[str]:
    if not evidence_ids:
        return []
    unique_ids = _unique_sorted_texts(evidence_ids)
    placeholders = ", ".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"""
        SELECT id, path
        FROM evidence
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        tuple(unique_ids),
    ).fetchall()
    return [str(row["path"]) for row in rows]


def _json_object_list(raw: object) -> list[dict[str, Any]]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _unique_sorted_texts(values: list[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def _active_needs_human_verifications(conn) -> list[dict[str, Any]]:
    placeholders = ", ".join("?" for _ in ACTIVE_RUN_STATUSES)
    return _rows(
        conn,
        f"""
        SELECT
          verifications.id,
          verifications.workflow_run_id,
          verifications.target_job_id,
          verifications.reasons_json,
          verifications.created_at
        FROM verifications
        INNER JOIN workflow_runs
          ON workflow_runs.id = verifications.workflow_run_id
        WHERE verifications.result = 'needs_human'
          AND workflow_runs.status IN ({placeholders})
        ORDER BY verifications.created_at ASC, verifications.id ASC
        """,
        tuple(sorted(ACTIVE_RUN_STATUSES)),
    )


def _json_string_list(raw: object) -> list[str]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _human_decision_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    severity = str(item.get("severity") or "")
    severity_rank = HUMAN_DECISION_SEVERITY_ORDER.get(severity, 99)
    created_at = str(item.get("created_at") or "~")
    item_id = str(item.get("id") or item.get("type") or item.get("kind") or "")
    return (severity_rank, created_at, item_id)


def _risk_summary(data: dict[str, Any], risk_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    validation = data.get("validation", {})
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])

    if errors:
        items.append(
            _risk_item(
                item_type="validation_errors",
                severity="critical",
                blocking=True,
                requires_human=False,
                summary=f"{len(errors)} validation error(s) must be resolved before trusting rendered state.",
                command="pcl validate --json",
                target_type="validation",
                target_id="",
                count=len(errors),
            )
        )
    if warnings:
        items.append(
            _risk_item(
                item_type="validation_warnings",
                severity="low",
                blocking=False,
                requires_human=False,
                summary=f"{len(warnings)} validation warning(s) need review.",
                command="pcl validate --json",
                target_type="validation",
                target_id="",
                count=len(warnings),
            )
        )

    action = data.get("next_action", {})
    if action.get("type") == "open_escalation":
        target = action.get("target", {})
        target_id = ""
        if isinstance(target, dict):
            target_id = str(target.get("verification_id") or target.get("workflow_run_id") or "")
        items.append(
            _risk_item(
                item_type="needs_human_verification",
                severity="high",
                blocking=True,
                requires_human=True,
                summary=str(action.get("reason", "A workflow verification needs human attention.")),
                command=str(action.get("command", "pcl next --json")),
                target_type="verification",
                target_id=target_id,
                count=1,
            )
        )

    for escalation in risk_rows["escalations"]:
        escalation_id = str(escalation.get("id", ""))
        items.append(
            _risk_item(
                item_type="open_escalation",
                severity=_normalize_severity(escalation.get("severity"), default="critical"),
                blocking=True,
                requires_human=True,
                summary=f"Open escalation {escalation_id}: {escalation.get('question', '')}",
                command=f"pcl escalation resolve {escalation_id} --summary 'Record the human decision'",
                target_type="escalation",
                target_id=escalation_id,
                count=1,
            )
        )

    for decision in risk_rows["decisions"]:
        decision_id = str(decision.get("id", ""))
        items.append(
            _risk_item(
                item_type="open_decision",
                severity="high",
                blocking=True,
                requires_human=True,
                summary=f"Open decision {decision_id}: {decision.get('question', '')}",
                command=f"pcl decision resolve {decision_id} --selected-option 'Record the choice' --reason 'Record the reason'",
                target_type="decision",
                target_id=decision_id,
                count=1,
            )
        )

    for defect in risk_rows["defects"]:
        defect_id = str(defect.get("id", ""))
        status = str(defect.get("status", ""))
        items.append(
            _risk_item(
                item_type="open_defect",
                severity=_normalize_severity(defect.get("severity"), default="medium"),
                blocking=False,
                requires_human=False,
                summary=f"Defect {defect_id} is {status}.",
                command=_defect_next_command(defect_id, status),
                target_type="defect",
                target_id=defect_id,
                count=1,
            )
        )

    for proposal in data.get("workflow_proposals", []):
        if proposal.get("status") != "proposed":
            continue
        proposal_id = str(proposal.get("id", ""))
        workflow_id = str(proposal.get("workflow_id", ""))
        items.append(
            _risk_item(
                item_type="workflow_proposal_review",
                severity="low",
                blocking=False,
                requires_human=True,
                summary=f"Workflow proposal {proposal_id} for {workflow_id} needs review.",
                command=f"pcl workflow proposals approve {proposal_id} --summary 'Approve this workflow template'",
                target_type="workflow_proposal",
                target_id=proposal_id,
                count=1,
            )
        )

    for run in risk_rows["workflow_runs"]:
        status = str(run.get("status", ""))
        run_id = str(run.get("id", ""))
        items.append(
            _risk_item(
                item_type=f"{status}_workflow_run",
                severity="high" if status == "failed" else "medium",
                blocking=status == "blocked",
                requires_human=status == "blocked",
                summary=f"Workflow run {run_id} is {status}.",
                command=f"pcl report run {run_id}",
                target_type="workflow_run",
                target_id=run_id,
                count=1,
            )
        )

    for job in risk_rows["agent_jobs"]:
        status = str(job.get("status", ""))
        job_id = str(job.get("id", ""))
        items.append(
            _risk_item(
                item_type=f"{status}_agent_job",
                severity="high" if status == "failed" else "medium",
                blocking=status == "blocked",
                requires_human=status == "blocked",
                summary=f"Agent job {job_id} is {status}.",
                command=f"pcl jobs read {job_id}",
                target_type="agent_job",
                target_id=job_id,
                count=1,
            )
        )

    highest = "none"
    for item in items:
        severity = str(item["severity"])
        if SEVERITY_RANKS[severity] > SEVERITY_RANKS[highest]:
            highest = severity

    return {
        "blocking": any(bool(item["blocking"]) for item in items),
        "highest_severity": highest,
        "items": items,
    }


def _risk_item(
    *,
    item_type: str,
    severity: str,
    blocking: bool,
    requires_human: bool,
    summary: str,
    command: str,
    target_type: str,
    target_id: str,
    count: int,
) -> dict[str, Any]:
    return {
        "type": item_type,
        "severity": severity,
        "blocking": blocking,
        "requires_human": requires_human,
        "summary": summary,
        "command": command,
        "target": {"type": target_type, "id": target_id},
        "count": count,
    }


def _normalize_severity(value: object, *, default: str) -> str:
    severity = str(value or default).lower()
    return severity if severity in SEVERITY_RANKS and severity != "none" else default


def _defect_next_command(defect_id: str, status: str) -> str:
    commands = {
        "open": f"pcl defect triage {defect_id} --summary 'Summarize impact and priority'",
        "triaged": f"pcl defect start {defect_id} --summary 'Begin repair work'",
        "in_progress": f"pcl defect fix {defect_id} --summary 'Summarize the fix' --evidence 'Test or commit evidence'",
        "fixed": f"pcl defect verify {defect_id} --summary 'Summarize verification' --verification V-0001",
        "verified": f"pcl defect close {defect_id} --summary 'Close verified defect' --evidence 'Verification evidence'",
    }
    return commands.get(status, f"pcl loop run defect_repair --defect {defect_id}")


def _table(
    rows: list[dict],
    columns: list[str],
    *,
    anchor_rows: bool = True,
    strings: dict[str, str] | None = None,
) -> str:
    strings = strings or dashboard_strings("en")
    if not rows:
        return f'<p class="muted">{html.escape(strings["empty.records"])}</p>'
    head = "".join(f"<th>{html.escape(_column_label(c, strings))}</th>" for c in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_cell(row, c)}</td>" for c in columns)
        anchor = _row_anchor(row) if anchor_rows else ""
        attrs = f' id="{anchor}"' if anchor else ""
        body_rows.append(f"<tr{attrs}>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _column_label(column: str, strings: dict[str, str]) -> str:
    return strings.get(f"column.{column}", column)


def _cell(row: dict, column: str) -> str:
    value = row.get(column, "") or ""
    if isinstance(value, list):
        return ", ".join(_linked_scalar(item, column) for item in value)
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return html.escape(str(value))
    return _linked_scalar(value, column)


def _linked_scalar(value: object, column: str) -> str:
    text = html.escape(str(value))
    if not value:
        return text
    value_text = str(value)
    if _is_path_column(column) and value_text:
        href = html.escape(value_text, quote=True)
        return f'<a href="{href}">{text}</a>'
    if column != "id" and _looks_like_entity_id(value_text):
        href = f"#row-{html.escape(_fragment(value_text), quote=True)}"
        return f'<a href="{href}">{text}</a>'
    return text


def _is_path_column(column: str) -> bool:
    return column in {"path", "prompt_path", "output_path"} or column.endswith("_path") or column.endswith("_paths")


def _looks_like_entity_id(value: str) -> bool:
    return value.startswith(ENTITY_ID_PREFIXES)


def _row_anchor(row: dict[str, Any]) -> str:
    row_id = row.get("id")
    return f"row-{_fragment(str(row_id))}" if row_id else ""


def _fragment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)


def _key_value_panel(
    row: dict[str, Any] | None,
    fields: list[str],
    empty: str,
    strings: dict[str, str],
) -> str:
    if row is None:
        return f'<p class="muted">{html.escape(empty)}</p>'
    items = []
    for field in fields:
        value = row.get(field, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        items.append(
            f"<dt>{html.escape(_column_label(field, strings))}</dt>"
            f"<dd>{html.escape(str(value or ''))}</dd>"
        )
    return f"<dl>{''.join(items)}</dl>"


def _validation_block(validation: dict[str, Any], strings: dict[str, str]) -> str:
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])
    if not errors and not warnings:
        return f'<p class="ok">{html.escape(strings["validation.ok"])}</p>'
    parts = []
    if errors:
        parts.append(f"<h3>{html.escape(strings['validation.errors'])}</h3>")
        parts.append("<ul>" + "".join(f"<li>{html.escape(str(error))}</li>" for error in errors) + "</ul>")
    if warnings:
        parts.append(f"<h3>{html.escape(strings['validation.warnings'])}</h3>")
        parts.append(
            "<ul>" + "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings) + "</ul>"
        )
    return "".join(parts)


def _risk_summary_block(summary: dict[str, Any], strings: dict[str, str]) -> str:
    items = summary.get("items", [])
    if not items:
        return f'<p class="ok">{html.escape(strings["risk.none"])}</p>'
    parts = [
        "<dl>",
        f"<dt>{html.escape(strings['risk.blocking'])}</dt>"
        f"<dd>{html.escape(_yes_no(bool(summary.get('blocking')), strings))}</dd>",
        f"<dt>{html.escape(strings['risk.highest_severity'])}</dt>"
        f"<dd>{html.escape(str(summary.get('highest_severity', 'none')))}</dd>",
        "</dl>",
        "<ul>",
    ]
    for item in items:
        target = item.get("target", {})
        target_label = ""
        if isinstance(target, dict):
            target_id = str(target.get("id") or "")
            target_type = str(target.get("type") or "")
            if target_id:
                target_label = f" [{target_type} {target_id}]"
        severity = html.escape(str(item.get("severity", "")))
        item_type = html.escape(str(item.get("type", "")))
        target_text = html.escape(target_label)
        summary_text = html.escape(str(item.get("summary", "")))
        command = html.escape(str(item.get("command", "")))
        parts.append(
            f"<li><strong>{severity}</strong> {item_type}{target_text}: {summary_text}"
            f"<br><code>{command}</code></li>"
        )
    parts.append("</ul>")
    return "".join(parts)


def _next_action_block(action: dict[str, Any], strings: dict[str, str]) -> str:
    command = html.escape(str(action.get("command") or ""))
    command_block = f"<p><code>{command}</code></p>" if command else ""
    reason = html.escape(str(action.get("reason", "")))
    action_type = html.escape(str(action.get("type", "")))
    priority = html.escape(str(action.get("priority", "")))
    blocking = html.escape(_yes_no(bool(action.get("blocking")), strings))
    requires_human = html.escape(_yes_no(bool(action.get("requires_human")), strings))
    safe_to_run = html.escape(_yes_no(bool(action.get("safe_to_run")), strings))
    run_policy = html.escape(str(action.get("run_policy", "")))
    human_guidance = html.escape(str(action.get("human_guidance", "")))
    expected_after = html.escape(str(action.get("expected_after", "")))
    return (
        f"<p><strong>{action_type}</strong></p>"
        f"<p>{reason}</p>"
        f"{command_block}"
        "<dl>"
        f"<dt>{html.escape(strings['next_action.priority'])}</dt><dd>{priority}</dd>"
        f"<dt>{html.escape(strings['next_action.blocking'])}</dt><dd>{blocking}</dd>"
        f"<dt>{html.escape(strings['next_action.requires_human'])}</dt><dd>{requires_human}</dd>"
        f"<dt>{html.escape(strings['next_action.safe_to_run'])}</dt><dd>{safe_to_run}</dd>"
        f"<dt>{html.escape(strings['next_action.run_policy'])}</dt><dd>{run_policy}</dd>"
        f"<dt>{html.escape(strings['next_action.human_guidance'])}</dt><dd>{human_guidance}</dd>"
        f"<dt>{html.escape(strings['next_action.expected_after'])}</dt><dd>{expected_after}</dd>"
        "</dl>"
    )


def _yes_no(value: bool, strings: dict[str, str]) -> str:
    return strings["yes"] if value else strings["no"]


def _budget_block(active_workflow: dict[str, Any] | None, strings: dict[str, str]) -> str:
    if active_workflow is None:
        return f'<p class="muted">{html.escape(strings["empty.budget"])}</p>'
    budget = active_workflow.get("budget", {})
    iteration = html.escape(str(active_workflow.get("iteration", "")))
    max_iterations = ""
    if isinstance(budget, dict):
        max_iterations = html.escape(str(budget.get("max_iterations", "")))
    detail = f"<p>{html.escape(strings['budget.iteration'])} <strong>{iteration}</strong>"
    if max_iterations:
        detail += f" {html.escape(strings['budget.of'])} <strong>{max_iterations}</strong>"
    detail += "</p>"
    if isinstance(budget, dict) and budget:
        detail += "<pre>" + html.escape(json.dumps(budget, ensure_ascii=False, indent=2, sort_keys=True)) + "</pre>"
    return detail


def _human_decisions_block(human_decisions: dict[str, Any], strings: dict[str, str]) -> str:
    items = human_decisions.get("items", [])
    if not items:
        return f'<p class="ok">{html.escape(strings["empty.human_decisions"])}</p>'

    parts = ['<div class="decision-list">']
    for item in items:
        parts.append('<article class="decision-card">')
        parts.append(f"<h3>{_human_decision_title(item, strings)}</h3>")

        details = _human_decision_details(item, strings)
        if details:
            parts.append(f"<dl>{''.join(details)}</dl>")

        question = str(item.get("question", ""))
        reason = str(item.get("reason", ""))
        reasons = item.get("reasons", [])
        why_blocked = str(item.get("why_blocked", ""))
        recommendation = str(item.get("recommendation", ""))
        recommendation_reason = str(item.get("recommendation_reason", ""))
        related_evidence_paths = item.get("related_evidence_paths", [])
        receipt_paths = item.get("receipt_paths", [])
        options = item.get("options", [])

        if question:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.question'])}:</strong> "
                f"{html.escape(question)}</p>"
            )
        if reason:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.reason'])}:</strong> "
                f"{html.escape(reason)}</p>"
            )
        if why_blocked:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.why_blocked'])}:</strong> "
                f"{html.escape(why_blocked)}</p>"
            )
        if isinstance(reasons, list) and reasons:
            rendered_reasons = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in reasons)
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.reasons'])}:</strong></p>"
                f"<ul>{rendered_reasons}</ul>"
            )
        if recommendation:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.recommendation'])}:</strong> "
                f"{html.escape(recommendation)}</p>"
            )
        if recommendation_reason:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.recommendation_reason'])}:</strong> "
                f"{html.escape(recommendation_reason)}</p>"
            )
        if isinstance(related_evidence_paths, list) and related_evidence_paths:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.related_evidence_paths'])}:</strong></p>"
                f"{_path_list(related_evidence_paths)}"
            )
        if isinstance(receipt_paths, list) and receipt_paths:
            parts.append(
                f"<p><strong>{html.escape(strings['human_decision.receipt_paths'])}:</strong></p>"
                f"{_path_list(receipt_paths)}"
            )
        parts.append(_human_decision_options_table(options, strings))
        parts.append("</article>")
    parts.append("</div>")
    return "".join(parts)


def _human_decision_title(item: dict[str, Any], strings: dict[str, str]) -> str:
    kind = str(item.get("kind", ""))
    label = strings.get(f"human_decision.kind.{kind}", kind)
    item_id = str(item.get("id") or item.get("type") or "")
    if item_id:
        return f"{html.escape(label)} <code>{html.escape(item_id)}</code>"
    return html.escape(label)


def _human_decision_options_table(options: object, strings: dict[str, str]) -> str:
    if not isinstance(options, list) or not options:
        return ""
    rows = []
    for option in options:
        if not isinstance(option, dict):
            continue
        label = html.escape(str(option.get("label", "")))
        command = html.escape(str(option.get("command", "")))
        why_safe = html.escape(str(option.get("why_safe", "")))
        risk_if_run = html.escape(str(option.get("risk_if_run", "")))
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td><code>{command}</code></td>"
            f"<td>{why_safe}</td>"
            f"<td>{risk_if_run}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    headers = [
        strings["human_decision.option.label"],
        strings["human_decision.option.command"],
        strings["human_decision.option.why_safe"],
        strings["human_decision.option.risk_if_run"],
    ]
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    return (
        f"<p><strong>{html.escape(strings['human_decision.options'])}:</strong></p>"
        f"<table class=\"decision-options\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _path_list(paths: list[object]) -> str:
    items = "".join(f"<li>{_linked_scalar(path, 'path')}</li>" for path in paths)
    return f"<ul>{items}</ul>"


def _human_decision_details(item: dict[str, Any], strings: dict[str, str]) -> list[str]:
    details = []
    for key, label_key in [
        ("severity", "human_decision.severity"),
        ("workflow_run_id", "human_decision.workflow_run"),
        ("created_at", "human_decision.created"),
    ]:
        value = str(item.get(key, ""))
        if value:
            details.append(
                f"<dt>{html.escape(strings[label_key])}</dt><dd>{html.escape(value)}</dd>"
            )
    for key, label_key in [
        ("linked_decision_ids", "human_decision.linked_decisions"),
        ("linked_escalation_ids", "human_decision.linked_escalations"),
    ]:
        value = item.get(key, [])
        if isinstance(value, list) and value:
            details.append(
                f"<dt>{html.escape(strings[label_key])}</dt>"
                f"<dd>{html.escape(', '.join(str(item_id) for item_id in value))}</dd>"
            )
    return details


def _render_html(data: dict, *, locale: str = "en") -> str:
    template = read_text_resource("templates/dashboard/dashboard.html")
    strings = dashboard_strings(locale)
    counts = data["counts"]
    replacements = {
        "{{ lang }}": html.escape(locale),
        "{{ title }}": html.escape(strings["title"]),
        "{{ label_generated_at }}": html.escape(strings["generated_at"]),
        "{{ label_source_db }}": html.escape(strings["source_db"]),
        "{{ label_rule }}": html.escape(strings["rule"]),
        "{{ rule_text }}": strings["rule_text"],
        "{{ heading_next_human_action }}": html.escape(strings["next_human_action"]),
        "{{ heading_validation }}": html.escape(strings["validation"]),
        "{{ heading_risk_and_blockers }}": html.escape(strings["risk_and_blockers"]),
        "{{ heading_needs_your_decision }}": html.escape(strings["needs_your_decision"]),
        "{{ heading_current_goal }}": html.escape(strings["current_goal"]),
        "{{ heading_active_workflow }}": html.escape(strings["active_workflow"]),
        "{{ heading_budget_usage }}": html.escape(strings["budget_usage"]),
        "{{ heading_active_agent_jobs }}": html.escape(strings["active_agent_jobs"]),
        "{{ heading_verification_results }}": html.escape(strings["verification_results"]),
        "{{ heading_decision_queue }}": html.escape(strings["decision_queue"]),
        "{{ heading_escalation_queue }}": html.escape(strings["escalation_queue"]),
        "{{ heading_evidence_links }}": html.escape(strings["evidence_links"]),
        "{{ heading_reports }}": html.escape(strings["reports"]),
        "{{ heading_workflow_proposals }}": html.escape(strings["workflow_proposals"]),
        "{{ heading_recent_events }}": html.escape(strings["recent_events"]),
        "{{ heading_goals }}": html.escape(strings["goals"]),
        "{{ heading_features }}": html.escape(strings["features"]),
        "{{ heading_story_coverage }}": html.escape(strings["story_coverage"]),
        "{{ heading_test_coverage }}": html.escape(strings["test_coverage"]),
        "{{ heading_defects }}": html.escape(strings["defects"]),
        "{{ heading_task_backlog }}": html.escape(strings["task_backlog"]),
        "{{ heading_workflow_runs }}": html.escape(strings["workflow_runs"]),
        "{{ heading_agent_jobs }}": html.escape(strings["agent_jobs"]),
        "{{ label_features_count }}": html.escape(strings["summary.features"]),
        "{{ label_user_stories_count }}": html.escape(strings["summary.user_stories"]),
        "{{ label_test_cases_count }}": html.escape(strings["summary.test_cases"]),
        "{{ label_open_defects_count }}": html.escape(strings["summary.open_defects"]),
        "{{ label_goals_count }}": html.escape(strings["summary.goals"]),
        "{{ label_open_decisions_count }}": html.escape(strings["summary.open_decisions"]),
        "{{ label_workflow_runs_count }}": html.escape(strings["summary.workflow_runs"]),
        "{{ label_queued_jobs_count }}": html.escape(strings["summary.queued_jobs"]),
        "{{ label_open_escalations_count }}": html.escape(strings["summary.open_escalations"]),
        "{{ label_workflow_proposals_count }}": html.escape(
            strings["summary.workflow_proposals"]
        ),
        "{{ generated_at }}": html.escape(data["generated_at"]),
        "{{ source_db }}": html.escape(data["source_db"]),
        "{{ features_count }}": str(counts["features"]),
        "{{ user_stories_count }}": str(counts["user_stories"]),
        "{{ test_cases_count }}": str(counts["test_cases"]),
        "{{ open_defects_count }}": str(counts["open_defects"]),
        "{{ goals_count }}": str(counts["goals"]),
        "{{ open_decisions_count }}": str(counts["open_decisions"]),
        "{{ workflow_runs_count }}": str(counts["workflow_runs"]),
        "{{ queued_jobs_count }}": str(counts["queued_jobs"]),
        "{{ open_escalations_count }}": str(counts["open_escalations"]),
        "{{ workflow_proposals_count }}": str(counts["workflow_proposals"]),
        "{{ validation_block }}": _validation_block(data["validation"], strings),
        "{{ next_action_block }}": _next_action_block(data["next_action"], strings),
        "{{ risk_summary_block }}": _risk_summary_block(data["risk_summary"], strings),
        "{{ human_decisions_block }}": _human_decisions_block(data["human_decisions"], strings),
        "{{ current_goal_panel }}": _key_value_panel(
            data["current_goal"],
            ["id", "title", "status", "updated_at", "completion_json", "budget_json"],
            strings["empty.current_goal"],
            strings,
        ),
        "{{ active_workflow_panel }}": _key_value_panel(
            data["active_workflow"],
            ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "summary"],
            strings["empty.active_workflow"],
            strings,
        ),
        "{{ active_agent_jobs_table }}": _table(
            data["active_agent_jobs"],
            [
                "id",
                "role",
                "status",
                "assigned_agent_id",
                "attempts",
                "lease_expires_at",
                "last_heartbeat_at",
                "prompt_path",
                "output_path",
                "evidence_ids",
                "latest_evidence_id",
                "summary",
            ],
            anchor_rows=False,
            strings=strings,
        ),
        "{{ budget_panel }}": _budget_block(data["active_workflow"], strings),
        "{{ features_table }}": _table(
            data["features"],
            ["id", "name", "surface", "status", "confidence", "updated_at"],
            strings=strings,
        ),
        "{{ user_stories_table }}": _table(
            data["user_stories"],
            ["id", "feature_id", "actor", "goal", "status", "updated_at"],
            strings=strings,
        ),
        "{{ test_cases_table }}": _table(
            data["test_cases"],
            ["id", "feature_id", "story_id", "type", "status", "last_run_id", "evidence_id", "updated_at"],
            strings=strings,
        ),
        "{{ defects_table }}": _table(
            data["defects"],
            ["id", "feature_id", "severity", "status", "expected", "actual", "updated_at"],
            strings=strings,
        ),
        "{{ tasks_table }}": _table(
            data["tasks"],
            [
                "id",
                "title",
                "status",
                "priority",
                "owner",
                "risk",
                "effort",
                "related_goal_id",
                "related_feature_id",
                "related_defect_id",
                "dependency_ids",
                "dependent_ids",
                "created_at",
                "updated_at",
            ],
            strings=strings,
        ),
        "{{ goals_table }}": _table(
            data["goals"],
            ["id", "title", "status", "updated_at"],
            strings=strings,
        ),
        "{{ workflow_runs_table }}": _table(
            data["workflow_runs"],
            ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "summary"],
            strings=strings,
        ),
        "{{ agent_jobs_table }}": _table(
            data["agent_jobs"],
            [
                "id",
                "workflow_run_id",
                "role",
                "status",
                "assigned_agent_id",
                "attempts",
                "lease_expires_at",
                "last_heartbeat_at",
                "prompt_path",
                "output_path",
                "evidence_ids",
                "latest_evidence_id",
                "summary",
            ],
            strings=strings,
        ),
        "{{ verifications_table }}": _table(
            data["verifications"],
            [
                "id",
                "workflow_run_id",
                "target_job_id",
                "target_job_evidence_ids",
                "workflow_report_path",
                "verifier_role",
                "result",
                "reasons_json",
                "created_at",
            ],
            strings=strings,
        ),
        "{{ decisions_table }}": _table(
            data["decisions"],
            [
                "id",
                "status",
                "question",
                "recommendation",
                "linked_escalation_ids",
                "selected_option",
                "reason",
                "blocks_json",
                "created_at",
            ],
            strings=strings,
        ),
        "{{ escalations_table }}": _table(
            data["escalations"],
            [
                "id",
                "workflow_run_id",
                "severity",
                "question",
                "recommendation",
                "linked_decision_ids",
                "status",
                "created_at",
            ],
            strings=strings,
        ),
        "{{ evidence_table }}": _table(
            data["evidence"],
            [
                "id",
                "type",
                "path",
                "related_agent_job_ids",
                "related_workflow_run_ids",
                "related_report_paths",
                "command",
                "summary",
                "skill_names",
                "skill_recorded_hashes",
                "skill_health",
                "created_at",
            ],
            strings=strings,
        ),
        "{{ recent_events_table }}": _table(
            data["recent_events"],
            ["id", "event_type", "entity_type", "entity_id", "created_at"],
            strings=strings,
        ),
        "{{ reports_table }}": _table(
            data["reports"],
            ["name", "path", "related_evidence_ids", "related_agent_job_ids", "related_workflow_run_ids"],
            strings=strings,
        ),
        "{{ workflow_proposals_table }}": _table(
            data["workflow_proposals"],
            [
                "id",
                "status",
                "workflow_id",
                "path",
                "workflow_path",
                "summary",
                "review_summary",
                "created_at",
                "reviewed_at",
                "parse_error",
            ],
            strings=strings,
        ),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template
