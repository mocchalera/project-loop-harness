from __future__ import annotations

import html
import json
from typing import Any

from .commands import next_action
from .db import connect, count_rows
from .guards import require_initialized
from .links import enrich_decisions_with_links, enrich_escalations_with_links
from .paths import ProjectPaths
from .resources import read_text_resource
from .validators import validate_project
from .workflow_proposals import list_workflow_proposals
from .workflows import enrich_jobs_with_evidence
from .workflow_yaml import parse_workflow_yaml


DASHBOARD_DATA_CONTRACT_VERSION = "dashboard-data/v1"
ENTITY_ID_PREFIXES = ("D-", "DEC-", "E-", "ESC-", "F-", "G-", "J-", "TC-", "US-", "V-", "WR-")
SEVERITY_RANKS = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _state_timestamp(conn) -> str:
    row = conn.execute("SELECT MAX(created_at) AS generated_at FROM events").fetchone()
    return str(row["generated_at"] or "")


def _one(conn, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def render_dashboard(paths: ProjectPaths) -> None:
    require_initialized(paths)
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
        data = {
            "contract_version": DASHBOARD_DATA_CONTRACT_VERSION,
            "generated_at": _state_timestamp(conn),
            "source_db": str(paths.db_path),
            "validation": validation.to_dict(),
            "next_action": next_action(paths),
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
                SELECT id, workflow_run_id, role, status, prompt_path, output_path, summary
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
            "goals": _rows(
                conn,
                """
                SELECT id, title, status, updated_at
                FROM goals
                ORDER BY created_at DESC, id DESC
                LIMIT 20
                """,
            ),
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
                SELECT id, workflow_run_id, role, status, prompt_path, output_path, summary
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
        _enrich_navigation(paths, data)
        data["risk_summary"] = _risk_summary(data, risk_rows)
    finally:
        conn.close()

    paths.dashboard_dir.mkdir(parents=True, exist_ok=True)
    paths.dashboard_data.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.dashboard_html.write_text(_render_html(data), encoding="utf-8")


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


def _table(rows: list[dict], columns: list[str], *, anchor_rows: bool = True) -> str:
    if not rows:
        return '<p class="muted">No records yet.</p>'
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{_cell(row, c)}</td>" for c in columns)
        anchor = _row_anchor(row) if anchor_rows else ""
        attrs = f' id="{anchor}"' if anchor else ""
        body_rows.append(f"<tr{attrs}>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


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


def _key_value_panel(row: dict[str, Any] | None, fields: list[str], empty: str) -> str:
    if row is None:
        return f'<p class="muted">{html.escape(empty)}</p>'
    items = []
    for field in fields:
        value = row.get(field, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        items.append(
            f"<dt>{html.escape(field)}</dt><dd>{html.escape(str(value or ''))}</dd>"
        )
    return f"<dl>{''.join(items)}</dl>"


def _validation_block(validation: dict[str, Any]) -> str:
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])
    if not errors and not warnings:
        return '<p class="ok">Validation OK</p>'
    parts = []
    if errors:
        parts.append("<h3>Validation Errors</h3>")
        parts.append("<ul>" + "".join(f"<li>{html.escape(str(error))}</li>" for error in errors) + "</ul>")
    if warnings:
        parts.append("<h3>Validation Warnings</h3>")
        parts.append(
            "<ul>" + "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings) + "</ul>"
        )
    return "".join(parts)


def _risk_summary_block(summary: dict[str, Any]) -> str:
    items = summary.get("items", [])
    if not items:
        return '<p class="ok">No risks or blockers detected.</p>'
    parts = [
        "<dl>",
        f"<dt>blocking</dt><dd>{html.escape(_yes_no(bool(summary.get('blocking'))))}</dd>",
        f"<dt>highest_severity</dt><dd>{html.escape(str(summary.get('highest_severity', 'none')))}</dd>",
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


def _next_action_block(action: dict[str, Any]) -> str:
    command = html.escape(str(action.get("command", "")))
    reason = html.escape(str(action.get("reason", "")))
    action_type = html.escape(str(action.get("type", "")))
    priority = html.escape(str(action.get("priority", "")))
    blocking = html.escape(_yes_no(bool(action.get("blocking"))))
    requires_human = html.escape(_yes_no(bool(action.get("requires_human"))))
    safe_to_run = html.escape(_yes_no(bool(action.get("safe_to_run"))))
    run_policy = html.escape(str(action.get("run_policy", "")))
    human_guidance = html.escape(str(action.get("human_guidance", "")))
    expected_after = html.escape(str(action.get("expected_after", "")))
    return (
        f"<p><strong>{action_type}</strong></p>"
        f"<p>{reason}</p>"
        f"<p><code>{command}</code></p>"
        "<dl>"
        f"<dt>priority</dt><dd>{priority}</dd>"
        f"<dt>blocking</dt><dd>{blocking}</dd>"
        f"<dt>requires_human</dt><dd>{requires_human}</dd>"
        f"<dt>safe_to_run</dt><dd>{safe_to_run}</dd>"
        f"<dt>run_policy</dt><dd>{run_policy}</dd>"
        f"<dt>human_guidance</dt><dd>{human_guidance}</dd>"
        f"<dt>expected_after</dt><dd>{expected_after}</dd>"
        "</dl>"
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _budget_block(active_workflow: dict[str, Any] | None) -> str:
    if active_workflow is None:
        return '<p class="muted">No active workflow budget.</p>'
    budget = active_workflow.get("budget", {})
    iteration = html.escape(str(active_workflow.get("iteration", "")))
    max_iterations = ""
    if isinstance(budget, dict):
        max_iterations = html.escape(str(budget.get("max_iterations", "")))
    detail = f"<p>Iteration <strong>{iteration}</strong>"
    if max_iterations:
        detail += f" of <strong>{max_iterations}</strong>"
    detail += "</p>"
    if isinstance(budget, dict) and budget:
        detail += "<pre>" + html.escape(json.dumps(budget, ensure_ascii=False, indent=2, sort_keys=True)) + "</pre>"
    return detail


def _render_html(data: dict) -> str:
    template = read_text_resource("templates/dashboard/dashboard.html")
    counts = data["counts"]
    replacements = {
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
        "{{ validation_block }}": _validation_block(data["validation"]),
        "{{ next_action_block }}": _next_action_block(data["next_action"]),
        "{{ risk_summary_block }}": _risk_summary_block(data["risk_summary"]),
        "{{ current_goal_panel }}": _key_value_panel(
            data["current_goal"],
            ["id", "title", "status", "updated_at", "completion_json", "budget_json"],
            "No open goal. Create one with `pcl goal create`.",
        ),
        "{{ active_workflow_panel }}": _key_value_panel(
            data["active_workflow"],
            ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "summary"],
            "No queued, running, or blocked workflow.",
        ),
        "{{ active_agent_jobs_table }}": _table(
            data["active_agent_jobs"],
            ["id", "role", "status", "prompt_path", "output_path", "evidence_ids", "latest_evidence_id", "summary"],
            anchor_rows=False,
        ),
        "{{ budget_panel }}": _budget_block(data["active_workflow"]),
        "{{ features_table }}": _table(data["features"], ["id", "name", "surface", "status", "confidence", "updated_at"]),
        "{{ user_stories_table }}": _table(data["user_stories"], ["id", "feature_id", "actor", "goal", "status", "updated_at"]),
        "{{ test_cases_table }}": _table(data["test_cases"], ["id", "feature_id", "story_id", "type", "status", "last_run_id", "evidence_id", "updated_at"]),
        "{{ defects_table }}": _table(data["defects"], ["id", "feature_id", "severity", "status", "expected", "actual", "updated_at"]),
        "{{ goals_table }}": _table(data["goals"], ["id", "title", "status", "updated_at"]),
        "{{ workflow_runs_table }}": _table(data["workflow_runs"], ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "summary"]),
        "{{ agent_jobs_table }}": _table(data["agent_jobs"], ["id", "workflow_run_id", "role", "status", "prompt_path", "output_path", "evidence_ids", "latest_evidence_id", "summary"]),
        "{{ verifications_table }}": _table(data["verifications"], ["id", "workflow_run_id", "target_job_id", "target_job_evidence_ids", "workflow_report_path", "verifier_role", "result", "reasons_json", "created_at"]),
        "{{ decisions_table }}": _table(data["decisions"], ["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "blocks_json", "created_at"]),
        "{{ escalations_table }}": _table(data["escalations"], ["id", "workflow_run_id", "severity", "question", "recommendation", "linked_decision_ids", "status", "created_at"]),
        "{{ evidence_table }}": _table(data["evidence"], ["id", "type", "path", "related_agent_job_ids", "related_workflow_run_ids", "related_report_paths", "command", "summary", "created_at"]),
        "{{ recent_events_table }}": _table(data["recent_events"], ["id", "event_type", "entity_type", "entity_id", "created_at"]),
        "{{ reports_table }}": _table(data["reports"], ["name", "path", "related_evidence_ids", "related_agent_job_ids", "related_workflow_run_ids"]),
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
        ),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template
