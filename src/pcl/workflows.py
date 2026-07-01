from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .commands import FEATURE_STATUSES, to_pretty_json
from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .stories import TEST_CASE_TYPES
from .timeutil import utc_now_iso
from .workflow_yaml import parse_workflow_yaml


@dataclass(frozen=True)
class WorkflowTemplate:
    workflow_id: str
    name: str
    workflow_type: str
    version: str
    path: Path
    data: dict[str, Any]

    @property
    def agents(self) -> dict[str, Any]:
        agents = self.data.get("agents", {})
        return agents if isinstance(agents, dict) else {}

    @property
    def steps(self) -> list[Any]:
        steps = self.data.get("steps", [])
        return steps if isinstance(steps, list) else []


def load_workflow_template(paths: ProjectPaths, workflow_id: str) -> WorkflowTemplate:
    _validate_identifier(workflow_id, "workflow_id")
    workflow_path = paths.workflows_dir / f"{workflow_id}.yaml"
    if not workflow_path.exists():
        raise InvalidInputError(
            f"Workflow template does not exist: {workflow_id}",
            details={"workflow_id": workflow_id, "path": str(workflow_path)},
        )

    data = parse_workflow_yaml(workflow_path.read_text(encoding="utf-8"))
    for field in ["id", "name", "type", "version", "goal", "agents", "steps", "budget", "stop_conditions"]:
        if field not in data:
            raise InvalidInputError(
                f"Workflow template {workflow_id} is missing required field: {field}",
                details={"workflow_id": workflow_id, "field": field},
            )
    if data["id"] != workflow_id:
        raise InvalidInputError(
            f"Workflow template id mismatch: expected {workflow_id}, found {data['id']}",
            details={"expected": workflow_id, "actual": data["id"]},
        )
    if not isinstance(data["agents"], dict):
        raise InvalidInputError(f"Workflow template {workflow_id} agents must be a mapping.")
    if not isinstance(data["steps"], list):
        raise InvalidInputError(f"Workflow template {workflow_id} steps must be a list.")
    return WorkflowTemplate(
        workflow_id=str(data["id"]),
        name=str(data["name"]),
        workflow_type=str(data["type"]),
        version=str(data["version"]),
        path=workflow_path,
        data=data,
    )


def run_workflow(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    goal_id: str | None = None,
    defect_id: str | None = None,
    iteration: int = 1,
    retry_of_workflow_run_id: str | None = None,
    retry_of_status: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    template = load_workflow_template(paths, workflow_id)
    conn = connect(paths.db_path)
    try:
        _validate_target(conn, goal_id=goal_id, defect_id=defect_id)
        _validate_retry_metadata(
            iteration=iteration,
            retry_of_workflow_run_id=retry_of_workflow_run_id,
            retry_of_status=retry_of_status,
        )
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO workflows(id, name, type, template_path, version, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name = excluded.name,
              type = excluded.type,
              template_path = excluded.template_path,
              version = excluded.version
            """,
            (
                template.workflow_id,
                template.name,
                template.workflow_type,
                str(template.path.relative_to(paths.root)),
                template.version,
                now,
            ),
        )
        run_id = next_prefixed_id(conn, "workflow_runs", "WR")
        conn.execute(
            """
            INSERT INTO workflow_runs(id, goal_id, workflow_id, status, iteration, started_at, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                goal_id,
                template.workflow_id,
                "queued",
                iteration,
                now,
                _run_summary(goal_id=goal_id, defect_id=defect_id),
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_run_created",
            entity_type="workflow_run",
            entity_id=run_id,
            payload={"workflow_id": workflow_id, "goal_id": goal_id, "defect_id": defect_id},
        )
        if retry_of_workflow_run_id:
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="workflow_execution_retried",
                entity_type="workflow_run",
                entity_id=run_id,
                payload={
                    "workflow_id": workflow_id,
                    "retry_of_workflow_run_id": retry_of_workflow_run_id,
                    "retry_of_status": retry_of_status,
                    "iteration": iteration,
                },
            )

        jobs: list[dict[str, Any]] = []
        for step in _agent_steps(template):
            job_id = next_prefixed_id(conn, "agent_jobs", "J")
            prompt_path = _prompt_path(paths, job_id)
            prompt_text = _render_prompt(
                template=template,
                run_id=run_id,
                job_id=job_id,
                step=step,
                goal_id=goal_id,
                defect_id=defect_id,
            )
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt_text, encoding="utf-8")
            role = str(step["agent"])
            conn.execute(
                """
                INSERT INTO agent_jobs(id, workflow_run_id, role, status, prompt_path, summary)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_id,
                    role,
                    "queued",
                    str(prompt_path.relative_to(paths.root)),
                    f"step:{step['id']}",
                ),
            )
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="agent_job_created",
                entity_type="agent_job",
                entity_id=job_id,
                payload={
                    "workflow_run_id": run_id,
                    "workflow_id": workflow_id,
                    "step_id": step["id"],
                    "role": role,
                    "prompt_path": str(prompt_path.relative_to(paths.root)),
                },
            )
            jobs.append(
                {
                    "id": job_id,
                    "workflow_run_id": run_id,
                    "role": role,
                    "status": "queued",
                    "step_id": step["id"],
                    "prompt_path": str(prompt_path.relative_to(paths.root)),
                }
            )
        conn.commit()
        return {
            "ok": True,
            "workflow_run": {
                "id": run_id,
                "workflow_id": workflow_id,
                "goal_id": goal_id,
                "defect_id": defect_id,
                "status": "queued",
                "iteration": iteration,
            },
            "jobs": jobs,
        }
    finally:
        conn.close()


JOB_STATUSES = {"queued", "running", "blocked", "failed", "passed", "cancelled"}
AGENT_OUTPUT_TEMPLATE = [
    "Return an `agent-output/v1` Markdown report. It must use this exact minimum shape:",
    "",
    "```markdown",
    "# Short result summary",
    "",
    "## Findings",
    "",
    "- Concrete findings, scoped to this job.",
    "",
    "## Evidence",
    "",
    "- Paths, commands, test results, screenshots, or files reviewed.",
    "",
    "## Recommended pcl Commands",
    "",
    "- Optional ready-to-review `pcl ...` commands for the operator.",
    "```",
    "",
    "The first non-empty line must be the H1 summary. `## Findings` and `## Evidence` are required for ingestion.",
]


def list_jobs(
    paths: ProjectPaths,
    *,
    workflow_run_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    require_initialized(paths)
    if workflow_run_id:
        _validate_identifier(workflow_run_id, "workflow_run_id")
    if status and status not in JOB_STATUSES:
        raise InvalidInputError(
            f"Invalid job status: {status}",
            details={"status": status, "allowed": sorted(JOB_STATUSES)},
        )
    conn = connect(paths.db_path)
    try:
        if workflow_run_id:
            run_exists = conn.execute(
                "SELECT 1 FROM workflow_runs WHERE id = ?",
                (workflow_run_id,),
            ).fetchone()
            if run_exists is None:
                raise InvalidInputError(
                    f"Workflow run does not exist: {workflow_run_id}",
                    details={"workflow_run_id": workflow_run_id},
                )
        where_clauses = []
        params: list[str] = []
        if workflow_run_id:
            where_clauses.append("agent_jobs.workflow_run_id = ?")
            params.append(workflow_run_id)
        if status:
            where_clauses.append("agent_jobs.status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        rows = conn.execute(
            f"""
            SELECT
              agent_jobs.id,
              agent_jobs.workflow_run_id,
              workflow_runs.workflow_id,
              agent_jobs.role,
              agent_jobs.status,
              agent_jobs.prompt_path,
              agent_jobs.output_path,
              agent_jobs.summary
            FROM agent_jobs
            JOIN workflow_runs ON workflow_runs.id = agent_jobs.workflow_run_id
            {where_sql}
            ORDER BY agent_jobs.id
            """,
            tuple(params),
        ).fetchall()
        jobs = [dict(row) for row in rows]
        enrich_jobs_with_evidence(conn, jobs)
        return jobs
    finally:
        conn.close()


def read_job(paths: ProjectPaths, job_id: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT
              agent_jobs.id,
              agent_jobs.workflow_run_id,
              workflow_runs.workflow_id,
              agent_jobs.role,
              agent_jobs.status,
              agent_jobs.prompt_path,
              agent_jobs.output_path,
              agent_jobs.summary
            FROM agent_jobs
            JOIN workflow_runs ON workflow_runs.id = agent_jobs.workflow_run_id
            WHERE agent_jobs.id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(f"Agent job does not exist: {job_id}", details={"job_id": job_id})
        job = dict(row)
        enrich_jobs_with_evidence(conn, [job])
    finally:
        conn.close()

    prompt_path = paths.root / str(job["prompt_path"])
    job["prompt"] = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    return job


def enrich_jobs_with_evidence(conn: sqlite3.Connection, jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        return
    job_ids = [str(job["id"]) for job in jobs]
    placeholders = ",".join("?" for _ in job_ids)
    event_rows = conn.execute(
        f"""
        SELECT entity_id, payload_json
        FROM events
        WHERE event_type = 'agent_output_ingested'
          AND entity_type = 'agent_job'
          AND entity_id IN ({placeholders})
        ORDER BY rowid
        """,
        tuple(job_ids),
    ).fetchall()
    evidence_ids_by_job: dict[str, list[str]] = {job_id: [] for job_id in job_ids}
    for row in event_rows:
        payload = _parse_payload(str(row["payload_json"] or "{}"))
        evidence_id = payload.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            ids = evidence_ids_by_job[str(row["entity_id"])]
            if evidence_id not in ids:
                ids.append(evidence_id)

    evidence_by_id = _evidence_by_id(conn, [eid for ids in evidence_ids_by_job.values() for eid in ids])
    for job in jobs:
        evidence_ids = evidence_ids_by_job.get(str(job["id"]), [])
        evidence = [evidence_by_id[evidence_id] for evidence_id in evidence_ids if evidence_id in evidence_by_id]
        latest = evidence[-1] if evidence else None
        job["evidence_ids"] = evidence_ids
        job["evidence"] = evidence
        job["latest_evidence_id"] = latest["id"] if latest else None
        job["latest_evidence_path"] = latest["path"] if latest else None


def _parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _evidence_by_id(conn: sqlite3.Connection, evidence_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not evidence_ids:
        return {}
    unique_ids = list(dict.fromkeys(evidence_ids))
    placeholders = ",".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"""
        SELECT id, type, path, command, summary, created_at
        FROM evidence
        WHERE id IN ({placeholders})
        """,
        tuple(unique_ids),
    ).fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def _agent_steps(template: WorkflowTemplate) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for raw in template.steps:
        if not isinstance(raw, dict):
            continue
        if "agent" not in raw:
            continue
        if "id" not in raw:
            raise InvalidInputError(
                f"Workflow {template.workflow_id} has an agent step without an id.",
                details={"workflow_id": template.workflow_id, "step": raw},
            )
        agent_id = str(raw["agent"])
        if agent_id not in template.agents:
            raise InvalidInputError(
                f"Workflow {template.workflow_id} step {raw['id']} references unknown agent: {agent_id}",
                details={"workflow_id": template.workflow_id, "agent": agent_id},
            )
        steps.append(raw)
    return steps


def _validate_target(conn, *, goal_id: str | None, defect_id: str | None) -> None:
    if goal_id:
        _validate_identifier(goal_id, "goal_id")
        row = conn.execute("SELECT id FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if row is None:
            raise InvalidInputError(f"Goal does not exist: {goal_id}", details={"goal_id": goal_id})
    if defect_id:
        _validate_identifier(defect_id, "defect_id")
        row = conn.execute("SELECT id FROM defects WHERE id = ?", (defect_id,)).fetchone()
        if row is None:
            raise InvalidInputError(f"Defect does not exist: {defect_id}", details={"defect_id": defect_id})


def _validate_retry_metadata(
    *,
    iteration: int,
    retry_of_workflow_run_id: str | None,
    retry_of_status: str | None,
) -> None:
    if iteration < 1:
        raise InvalidInputError(
            "Workflow run iteration must be at least 1.",
            details={"iteration": iteration},
        )
    if retry_of_workflow_run_id:
        _validate_identifier(retry_of_workflow_run_id, "retry_of_workflow_run_id")
        if not retry_of_status:
            raise InvalidInputError(
                "Retry workflow run metadata requires retry_of_status.",
                details={"retry_of_workflow_run_id": retry_of_workflow_run_id},
            )
    elif retry_of_status:
        raise InvalidInputError(
            "retry_of_status requires retry_of_workflow_run_id.",
            details={"retry_of_status": retry_of_status},
        )


def _validate_identifier(value: str, field_name: str) -> None:
    if not re_match_identifier(value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )


def re_match_identifier(value: str) -> bool:
    return bool(value) and all(c.isalnum() or c in {"_", "-"} for c in value)


def _run_summary(*, goal_id: str | None, defect_id: str | None) -> str:
    targets: list[str] = []
    if goal_id:
        targets.append(f"goal={goal_id}")
    if defect_id:
        targets.append(f"defect={defect_id}")
    return " ".join(targets)


def _prompt_path(paths: ProjectPaths, job_id: str) -> Path:
    return paths.evidence_dir / "agent-runs" / job_id / "prompt.md"


def _render_prompt(
    *,
    template: WorkflowTemplate,
    run_id: str,
    job_id: str,
    step: dict[str, Any],
    goal_id: str | None,
    defect_id: str | None,
) -> str:
    agent_id = str(step["agent"])
    agent = template.agents[agent_id]
    prompt = [
        f"# Agent Job {job_id}",
        "",
        f"- Workflow: {template.workflow_id} ({template.name})",
        f"- Workflow run: {run_id}",
        f"- Step: {step['id']}",
        f"- Role: {agent_id}",
        f"- Mode: {agent.get('mode', 'unspecified')}",
    ]
    if goal_id:
        prompt.append(f"- Goal: {goal_id}")
    if defect_id:
        prompt.append(f"- Defect: {defect_id}")
    prompt.extend(
        [
            "",
            "## Purpose",
            str(agent.get("purpose", "")),
            "",
            "## Step Contract",
            "```json",
            to_pretty_json(step),
            "```",
            "",
            "## Rules",
            "- Do not edit `.project-loop/project.db` directly.",
            "- Do not edit generated dashboard HTML directly.",
            "- Use `pcl` commands for state changes.",
            "- Preserve evidence paths for completion claims.",
            "- Do not execute commands unless the human or harness explicitly asks for it.",
            f"- Valid `pcl test plan --type` values: {_format_allowed_values(TEST_CASE_TYPES)}.",
            f"- Valid `pcl feature status --status` values: {_format_allowed_values(FEATURE_STATUSES)}.",
            "- `pcl test pass` and `pcl test fail` evidence should be command output, an artifact path, a screenshot path, a commit, or a report path.",
            "",
            "## Expected Output",
            *AGENT_OUTPUT_TEMPLATE,
            "",
            *_workflow_specific_handoff(template=template, step=step),
        ]
    )
    return "\n".join(prompt)


def _workflow_specific_handoff(*, template: WorkflowTemplate, step: dict[str, Any]) -> list[str]:
    if template.workflow_id != "feature_coverage":
        return []
    step_id = str(step.get("id", ""))
    if step_id == "map_surfaces":
        return [
            "## Feature Coverage Handoff",
            "- For each concrete feature candidate, include a ready-to-review command:",
            '  `pcl feature add --name "..." --surface "..." --description "..."`',
            "- Prefer small user-visible features over broad subsystem labels.",
            "- Include file paths or UI surfaces as evidence for each candidate.",
            "",
        ]
    if step_id == "generate_stories":
        return [
            "## Feature Coverage Handoff",
            "- If feature IDs are known, include ready-to-review story commands:",
            '  `pcl story draft --feature F-0001 --actor "..." --goal "..." --expected-behavior "..."`',
            "- Keep one story focused on one actor goal and expected behavior.",
            "",
        ]
    if step_id == "generate_tests":
        return [
            "## Feature Coverage Handoff",
            "- If feature IDs are known, include ready-to-review test commands:",
            '  `pcl test plan --feature F-0001 --type acceptance --scenario "..." --expected "..."`',
            "- If implementation or UX verification already happened, list build, test, and screenshot evidence paths.",
            "- Evidence can later be attached with:",
            '  `pcl feature status F-0001 --status done --summary "..." --evidence "..."`',
            "",
        ]
    return []


def _format_allowed_values(values: set[str]) -> str:
    return ", ".join(sorted(values))
