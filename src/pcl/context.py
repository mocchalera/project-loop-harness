from __future__ import annotations

import json
from typing import Any

from .db import connect
from .errors import InvalidInputError
from .guards import require_initialized
from .links import enrich_decisions_with_links, enrich_escalations_with_links
from .paths import ProjectPaths
from .workflows import list_jobs, read_job


CONTEXT_PACK_CONTRACT_VERSION = "context-pack/v1"
DEFAULT_MAX_TOKENS = 12000
APPROX_CHARS_PER_TOKEN = 4


def pack_context_for_job(
    paths: ProjectPaths,
    *,
    job_id: str,
    reader_role: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    if max_tokens < 1:
        raise InvalidInputError(
            "--max-tokens must be a positive integer.",
            details={"max_tokens": max_tokens},
        )

    job = read_job(paths, job_id)
    role = (reader_role or str(job["role"])).strip()
    approx_char_limit = max_tokens * APPROX_CHARS_PER_TOKEN

    conn = connect(paths.db_path)
    try:
        workflow_run_id = str(job["workflow_run_id"])
        run = _one(
            conn,
            """
            SELECT id, goal_id, workflow_id, status, iteration, started_at, ended_at, summary
            FROM workflow_runs
            WHERE id = ?
            """,
            (workflow_run_id,),
        )
        if run is None:
            raise InvalidInputError(
                f"Workflow run does not exist: {workflow_run_id}",
                details={"workflow_run_id": workflow_run_id},
            )
        goal = None
        if run.get("goal_id"):
            goal = _one(
                conn,
                """
                SELECT id, title, status, completion_json, stop_conditions_json, budget_json, created_at, updated_at
                FROM goals
                WHERE id = ?
                """,
                (str(run["goal_id"]),),
            )
        verifications = _rows(
            conn,
            """
            SELECT id, workflow_run_id, target_job_id, verifier_role, result, reasons_json, created_at
            FROM verifications
            WHERE workflow_run_id = ?
            ORDER BY created_at, id
            """,
            (workflow_run_id,),
        )
        escalations = _rows(
            conn,
            """
            SELECT id, workflow_run_id, severity, question, recommendation, status, created_at, resolved_at
            FROM escalations
            WHERE workflow_run_id = ?
            ORDER BY created_at, id
            """,
            (workflow_run_id,),
        )
        decisions = _decisions_for_escalations(conn, [str(escalation["id"]) for escalation in escalations])
        escalations = enrich_escalations_with_links(escalations, decisions)
        events = _events_for_target(
            conn,
            entities=[
                ("agent_job", job_id),
                ("workflow_run", workflow_run_id),
                *([("goal", str(run["goal_id"]))] if run.get("goal_id") else []),
            ],
        )
    finally:
        conn.close()

    jobs = list_jobs(paths, workflow_run_id=workflow_run_id)
    source_commands = [
        f"pcl jobs read {job_id} --json",
        f"pcl prompt job {job_id} --json",
        "pcl validate --json",
    ]
    source_paths = [str(job["prompt_path"])]
    if job.get("output_path"):
        source_paths.append(str(job["output_path"]))
    for evidence in _job_evidence(jobs):
        path = str(evidence.get("path") or "")
        if path and path not in source_paths:
            source_paths.append(path)

    sections = _build_sections(
        job=job,
        run=run,
        goal=goal,
        jobs=jobs,
        verifications=verifications,
        escalations=escalations,
        decisions=decisions,
        events=events,
    )
    markdown, included_sections, omitted_sections = _render_with_budget(
        title=f"# Context Pack: {job_id}",
        sections=sections,
        char_limit=approx_char_limit,
    )

    return {
        "contract_version": CONTEXT_PACK_CONTRACT_VERSION,
        "target": {"type": "agent_job", "id": job_id},
        "reader_role": role,
        "budget": {
            "max_tokens": max_tokens,
            "approx_char_limit": approx_char_limit,
            "approx_chars_per_token": APPROX_CHARS_PER_TOKEN,
        },
        "approx_char_count": len(markdown),
        "truncated": bool(omitted_sections),
        "included_sections": included_sections,
        "omitted_sections": omitted_sections,
        "source_commands": source_commands,
        "source_paths": source_paths,
        "markdown": markdown,
    }


def _build_sections(
    *,
    job: dict[str, Any],
    run: dict[str, Any],
    goal: dict[str, Any] | None,
    jobs: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    escalations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    return [
        (
            "machine_context_rules",
            "\n".join(
                [
                    "## Machine Context Rules",
                    "",
                    "- Treat this context pack as a focused handoff, not as complete project memory.",
                    "- Do not read or parse `.project-loop/dashboard/dashboard.html` as machine context.",
                    "- Use `pcl` JSON commands, reports, evidence paths, or `.project-loop/dashboard/dashboard-data.json` for follow-up context.",
                    "- Do not edit `.project-loop/project.db` directly.",
                    "",
                ]
            ),
        ),
        ("target_job", "## Target Job\n\n" + _kv_table(job, ["id", "workflow_run_id", "workflow_id", "role", "status", "prompt_path", "output_path", "summary"])),
        ("workflow_run", "## Workflow Run\n\n" + _kv_table(run, ["id", "workflow_id", "goal_id", "status", "iteration", "started_at", "ended_at", "summary"])),
        (
            "goal",
            "## Goal\n\n"
            + (
                _kv_table(goal, ["id", "title", "status", "completion_json", "budget_json", "updated_at"])
                if goal
                else "No goal is linked to this workflow run."
            ),
        ),
        ("run_jobs", "## Jobs In This Run\n\n" + _table(jobs, ["id", "role", "status", "prompt_path", "output_path", "latest_evidence_id", "summary"])),
        (
            "verifications",
            "## Verifications\n\n"
            + _table(verifications, ["id", "target_job_id", "verifier_role", "result", "reasons_json", "created_at"]),
        ),
        (
            "human_queue",
            "## Human Queue\n\n"
            + "### Escalations\n\n"
            + _table(escalations, ["id", "severity", "status", "question", "recommendation", "linked_decision_ids", "created_at"])
            + "\n\n### Decisions\n\n"
            + _table(decisions, ["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "created_at"]),
        ),
        ("evidence", "## Evidence\n\n" + _table(_job_evidence(jobs), ["id", "type", "path", "command", "summary", "created_at"])),
        ("recent_events", "## Recent Events\n\n" + _table(events, ["id", "event_type", "entity_type", "entity_id", "created_at", "payload_json"])),
        (
            "agent_prompt",
            "## Agent Prompt\n\n"
            + "````markdown\n"
            + str(job.get("prompt") or "").rstrip()
            + "\n````",
        ),
    ]


def _render_with_budget(
    *,
    title: str,
    sections: list[tuple[str, str]],
    char_limit: int,
) -> tuple[str, list[str], list[str]]:
    markdown = f"{title}\n\n"
    included: list[str] = []
    omitted: list[str] = []
    for section_id, section in sections:
        section_text = section.rstrip() + "\n\n"
        if len(markdown) + len(section_text) <= char_limit:
            markdown += section_text
            included.append(section_id)
        else:
            omitted.append(section_id)

    if omitted:
        note = "_Context truncated. Increase `--max-tokens` to include omitted sections._\n"
        if len(markdown) + len(note) <= char_limit:
            markdown += note

    if len(markdown) > char_limit:
        markdown = markdown[:char_limit]
    return markdown.rstrip() + "\n", included, omitted


def _decisions_for_escalations(conn, escalation_ids: list[str]) -> list[dict[str, Any]]:
    if not escalation_ids:
        return []
    decisions = enrich_decisions_with_links(
        _rows(
            conn,
            """
            SELECT id, status, question, recommendation, selected_option, reason, blocks_json, created_at, resolved_at
            FROM decisions
            ORDER BY created_at, id
            """,
        )
    )
    escalation_id_set = set(escalation_ids)
    return [
        decision
        for decision in decisions
        if escalation_id_set.intersection(decision.get("linked_escalation_ids", []))
    ]


def _events_for_target(conn, *, entities: list[tuple[str, str]], limit: int = 20) -> list[dict[str, Any]]:
    if not entities:
        return []
    clauses = " OR ".join("(entity_type = ? AND entity_id = ?)" for _ in entities)
    params: list[str] = []
    for entity_type, entity_id in entities:
        params.extend([entity_type, entity_id])
    params.append(str(limit))
    return _rows(
        conn,
        f"""
        SELECT id, event_type, entity_type, entity_id, payload_json, created_at
        FROM events
        WHERE {clauses}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    )


def _job_evidence(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in jobs:
        for item in job.get("evidence", []):
            evidence_id = str(item.get("id") or "")
            if evidence_id and evidence_id not in seen:
                evidence.append(item)
                seen.add(evidence_id)
    return evidence


def _one(conn, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def _rows(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _kv_table(row: dict[str, Any], keys: list[str]) -> str:
    lines = ["| Field | Value |", "|---|---|"]
    for key in keys:
        lines.append(f"| {_escape_cell(key)} | {_escape_cell(_stringify(row.get(key)))} |")
    return "\n".join(lines)


def _table(rows: list[dict[str, Any]], keys: list[str]) -> str:
    if not rows:
        return "None."
    lines = [
        "| " + " | ".join(_escape_cell(key) for key in keys) + " |",
        "| " + " | ".join("---" for _ in keys) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape_cell(_stringify(row.get(key))) for key in keys) + " |")
    return "\n".join(lines)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or any(ch.isspace() for ch in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={field_name: value},
        )
