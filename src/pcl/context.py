from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
import shlex
from typing import Any

from .code_context.summary import (
    CODE_CONTEXT_SUMMARY_VERSION,
    format_verification_suggestion_for_display,
    recommended_refresh_commands,
    refresh_replay,
    render_receipt_age_lines,
    summarize_code_context_receipt,
    summary_with_receipt_age,
)
from .code_context.receipts import (
    CONTEXT_RECEIPT_EVIDENCE_TYPE,
    evidence_ref_by_id,
    latest_context_receipt_ref,
    resolve_context_receipt_path,
)
from .context_binding import _receipt_target_binding_agrees
from .db import connect, table_exists
from .errors import ContextPackBudgetError, EXIT_USAGE, InvalidInputError, PclError
from .evidence import newest_linked_evidence_id
from .guards import require_initialized
from .links import enrich_decisions_with_links, enrich_escalations_with_links
from .paths import ProjectPaths
from .rubric import claims_rubric_v1
from .tasks import COMPLETED_DEPENDENCY_STATUSES, read_task
from .token_estimation import TOKEN_ESTIMATOR, estimate_token_count
from .workflows import list_jobs, read_job


CONTEXT_PACK_CONTRACT_VERSION = "context-pack/v1"
DEFAULT_MAX_TOKENS = 12000
LEGACY_APPROX_CHARS_PER_TOKEN = 4
MACHINE_CONTEXT_RULES_SECTION_ID = "machine_context_rules"
CODE_CONTEXT_SAFETY_SECTION_ID = "code_context_safety"
CODE_CONTEXT_DETAIL_SECTION_ID = "code_context_detail"
CODE_CONTEXT_VERIFICATION_SECTION_ID = "code_context_verification_suggestions"
CODE_CONTEXT_LINK_ROLE = "code_context"
TRUNCATION_NOTE = "_Context truncated. Increase `--max-tokens` to include omitted sections._\n"


class ContextPackBoundReceiptRequiredError(PclError):
    def __init__(self, *, target_type: str, target_id: str, suggested_refresh_command: str) -> None:
        super().__init__(
            message=f"No target-bound code context receipt exists for {target_type} {target_id}.",
            code="context_pack_bound_receipt_required",
            exit_code=EXIT_USAGE,
            details={
                "target_type": target_type,
                "target_id": target_id,
                "suggested_refresh_commands": [suggested_refresh_command],
            },
        )


class ContextPackBoundReceiptMismatchError(PclError):
    def __init__(
        self,
        *,
        target_type: str,
        target_id: str,
        evidence_id: str,
        claimed_target_binding: Any,
        suggested_refresh_command: str,
    ) -> None:
        super().__init__(
            message=(
                f"Linked code context receipt {evidence_id} for {target_type} {target_id} "
                "has a target_binding that disagrees with the evidence link routing row."
            ),
            code="context_pack_bound_receipt_mismatch",
            exit_code=EXIT_USAGE,
            details={
                "target_type": target_type,
                "target_id": target_id,
                "evidence_id": evidence_id,
                "claimed_target_binding": claimed_target_binding,
                "suggested_refresh_commands": [suggested_refresh_command],
            },
        )


JOB_SECTION_ORDER = [
    "machine_context_rules",
    "target_job",
    "workflow_run",
    "goal",
    "run_jobs",
    "verifications",
    "human_queue",
    "evidence",
    "recent_events",
    "agent_prompt",
]
TASK_SECTION_ORDER = [
    "machine_context_rules",
    "target_task",
    "dependencies",
    "dependents",
    "goal",
    "related_feature",
    "related_defect",
    "sibling_tasks",
    "recent_events",
]

JOB_SECTION_PRIORITY_PROFILES = {
    "implementer": {
        section_id: (
            10000
            if section_id == MACHINE_CONTEXT_RULES_SECTION_ID
            else 900 - index * 50
        )
        for index, section_id in enumerate(JOB_SECTION_ORDER)
    }
    | {
        CODE_CONTEXT_SAFETY_SECTION_ID: 10000,
        CODE_CONTEXT_DETAIL_SECTION_ID: 825,
        CODE_CONTEXT_VERIFICATION_SECTION_ID: 775,
    },
    "verifier": {
        "machine_context_rules": 10000,
        "code_context_safety": 10000,
        "verifications": 950,
        "code_context_verification_suggestions": 925,
        "evidence": 900,
        "target_job": 850,
        "run_jobs": 800,
        "code_context_detail": 775,
        "workflow_run": 750,
        "goal": 700,
        "human_queue": 650,
        "recent_events": 600,
        "agent_prompt": 550,
    },
    "pm": {
        "machine_context_rules": 10000,
        "code_context_safety": 10000,
        "goal": 950,
        "human_queue": 900,
        "workflow_run": 850,
        "verifications": 800,
        "code_context_verification_suggestions": 775,
        "target_job": 750,
        "run_jobs": 700,
        "evidence": 650,
        "code_context_detail": 625,
        "agent_prompt": 600,
        "recent_events": 550,
    },
}
TASK_SECTION_PRIORITY_PROFILES = {
    "default": {
        section_id: (
            10000
            if section_id == MACHINE_CONTEXT_RULES_SECTION_ID
            else 900 - index * 50
        )
        for index, section_id in enumerate(TASK_SECTION_ORDER)
    }
    | {
        CODE_CONTEXT_SAFETY_SECTION_ID: 10000,
        CODE_CONTEXT_DETAIL_SECTION_ID: 825,
        CODE_CONTEXT_VERIFICATION_SECTION_ID: 775,
        "linked_evidence": 830,
    }
}


def pack_context_for_job(
    paths: ProjectPaths,
    *,
    job_id: str,
    now: str,
    reader_role: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    include_code_context: bool = False,
    require_bound_receipt: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    if max_tokens < 1:
        raise InvalidInputError(
            "--max-tokens must be a positive integer.",
            details={"max_tokens": max_tokens},
        )
    if require_bound_receipt and not include_code_context:
        raise InvalidInputError(
            "--require-bound-receipt is valid only with --include-code-context.",
            details={"require_bound_receipt": True, "include_code_context": include_code_context},
        )

    job = read_job(paths, job_id)
    role = (reader_role or str(job["role"])).strip()
    role_profile, section_priorities = _job_role_profile(role)
    approx_char_limit = max_tokens * LEGACY_APPROX_CHARS_PER_TOKEN

    target = {"type": "agent_job", "id": job_id}
    code_context = (
        _latest_code_context_summary(
            paths,
            target_type=target["type"],
            target_id=target["id"],
            now=now,
            require_bound_receipt=require_bound_receipt,
        )
        if include_code_context
        else None
    )

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
            SELECT id, workflow_run_id, target_job_id, verifier_role, rubric_json, result, reasons_json, created_at
            FROM verifications
            WHERE workflow_run_id = ?
            ORDER BY created_at, id
            """,
            (workflow_run_id,),
        )
        _add_verification_rubric_columns(verifications)
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
    if code_context:
        receipt_path = _code_context_receipt_path(code_context)
        if receipt_path:
            source_paths.append(receipt_path)
    for evidence in _job_evidence(jobs):
        path = str(evidence.get("path") or "")
        if path and path not in source_paths:
            source_paths.append(path)

    sections = _build_job_sections(
        job=job,
        run=run,
        goal=goal,
        jobs=jobs,
        verifications=verifications,
        escalations=escalations,
        decisions=decisions,
        events=events,
        code_context=code_context,
    )
    markdown, included_sections, omitted_sections, required_sections = _render_with_budget(
        title=f"# Context Pack: {job_id}",
        sections=sections,
        max_tokens=max_tokens,
        section_priorities=section_priorities,
    )
    estimated_token_count = estimate_token_count(markdown)

    pack = {
        "contract_version": CONTEXT_PACK_CONTRACT_VERSION,
        "target": target,
        "reader_role": role,
        "role_profile": role_profile,
        "token_estimator": TOKEN_ESTIMATOR,
        "budget": {
            "max_tokens": max_tokens,
            "approx_char_limit": approx_char_limit,
            "approx_chars_per_token": LEGACY_APPROX_CHARS_PER_TOKEN,
            "token_estimator": TOKEN_ESTIMATOR,
        },
        "approx_char_count": len(markdown),
        "estimated_token_count": estimated_token_count,
        "truncated": bool(omitted_sections),
        "included_sections": included_sections,
        "omitted_sections": omitted_sections,
        "required_sections": required_sections,
        "required_sections_omitted": [],
        "source_commands": source_commands,
        "source_paths": source_paths,
        "markdown": markdown,
    }
    if code_context:
        pack["code_context"] = code_context
    if include_code_context:
        pack["suggested_refresh_commands"] = recommended_refresh_commands(
            code_context or {}
        )
    return pack


def pack_context_for_task(
    paths: ProjectPaths,
    *,
    task_id: str,
    now: str,
    reader_role: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    include_code_context: bool = False,
    require_bound_receipt: bool = False,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(task_id, "task_id")
    if max_tokens < 1:
        raise InvalidInputError(
            "--max-tokens must be a positive integer.",
            details={"max_tokens": max_tokens},
        )
    if require_bound_receipt and not include_code_context:
        raise InvalidInputError(
            "--require-bound-receipt is valid only with --include-code-context.",
            details={"require_bound_receipt": True, "include_code_context": include_code_context},
        )

    task = read_task(paths, task_id)
    role = (reader_role or "default").strip() or "default"
    role_profile, section_priorities = _task_role_profile(role)
    approx_char_limit = max_tokens * LEGACY_APPROX_CHARS_PER_TOKEN

    target = {"type": "task", "id": task_id}
    code_context = (
        _latest_code_context_summary(
            paths,
            target_type=target["type"],
            target_id=target["id"],
            now=now,
            require_bound_receipt=require_bound_receipt,
        )
        if include_code_context
        else None
    )

    conn = connect(paths.db_path)
    try:
        goal = _goal_for_task(conn, task)
        feature = _feature_for_task(conn, task)
        defect = _defect_for_task(conn, task)
        siblings = _sibling_tasks(conn, task) if task.get("related_goal_id") else []
        linked_evidence = _linked_task_evidence(paths, conn, task_id)
        event_entities = [("task", task_id)]
        if task.get("related_goal_id"):
            event_entities.append(("goal", str(task["related_goal_id"])))
        events = _events_for_target(conn, entities=event_entities)
    finally:
        conn.close()

    sections = _build_task_sections(
        task=task,
        goal=goal,
        feature=feature,
        defect=defect,
        siblings=siblings,
        linked_evidence=linked_evidence,
        events=events,
        code_context=code_context,
    )
    markdown, included_sections, omitted_sections, required_sections = _render_with_budget(
        title=f"# Context Pack: {task_id}",
        sections=sections,
        max_tokens=max_tokens,
        section_priorities=section_priorities,
    )
    estimated_token_count = estimate_token_count(markdown)

    source_paths = []
    source_paths.extend(_linked_task_evidence_source_paths(linked_evidence))
    if code_context:
        receipt_path = _code_context_receipt_path(code_context)
        if receipt_path:
            source_paths.append(receipt_path)

    pack = {
        "contract_version": CONTEXT_PACK_CONTRACT_VERSION,
        "target": target,
        "reader_role": role,
        "role_profile": role_profile,
        "token_estimator": TOKEN_ESTIMATOR,
        "budget": {
            "max_tokens": max_tokens,
            "approx_char_limit": approx_char_limit,
            "approx_chars_per_token": LEGACY_APPROX_CHARS_PER_TOKEN,
            "token_estimator": TOKEN_ESTIMATOR,
        },
        "approx_char_count": len(markdown),
        "estimated_token_count": estimated_token_count,
        "truncated": bool(omitted_sections),
        "included_sections": included_sections,
        "omitted_sections": omitted_sections,
        "required_sections": required_sections,
        "required_sections_omitted": [],
        "source_commands": [
            f"pcl task read {task_id} --json",
            "pcl task list --json",
            "pcl validate --json",
        ],
        "source_paths": source_paths,
        "markdown": markdown,
    }
    if linked_evidence:
        pack["linked_evidence"] = linked_evidence
    if code_context:
        pack["code_context"] = code_context
    if include_code_context:
        pack["suggested_refresh_commands"] = recommended_refresh_commands(
            code_context or {}
        )
    return pack


def _build_job_sections(
    *,
    job: dict[str, Any],
    run: dict[str, Any],
    goal: dict[str, Any] | None,
    jobs: list[dict[str, Any]],
    verifications: list[dict[str, Any]],
    escalations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    code_context: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    sections = [
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
    ]
    if code_context is not None:
        sections.extend(_code_context_sections(code_context))
    sections.extend(
        [
        (
            "target_job",
            "## Target Job\n\n"
            + _kv_table(
                job,
                [
                    "id",
                    "workflow_run_id",
                    "workflow_id",
                    "role",
                    "status",
                    "assigned_agent_id",
                    "attempts",
                    "lease_expires_at",
                    "last_heartbeat_at",
                    "prompt_path",
                    "output_path",
                    "summary",
                ],
            ),
        ),
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
            + _table(
                verifications,
                [
                    "id",
                    "target_job_id",
                    "verifier_role",
                    "result",
                    "confidence_score",
                    "evidence_completeness",
                    "reasons_json",
                    "created_at",
                ],
            ),
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
    )
    return sections


def _build_task_sections(
    *,
    task: dict[str, Any],
    goal: dict[str, Any] | None,
    feature: dict[str, Any] | None,
    defect: dict[str, Any] | None,
    siblings: list[dict[str, Any]],
    linked_evidence: list[dict[str, Any]],
    events: list[dict[str, Any]],
    code_context: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    sections = [
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
    ]
    if code_context is not None:
        sections.extend(_code_context_sections(code_context))
    sections.extend(
        [
        (
            "target_task",
            "## Target Task\n\n"
            + _kv_table(
                task,
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
                    "created_at",
                    "updated_at",
                ],
            )
            + "\n\n### Description\n\n"
            + "````markdown\n"
            + str(task.get("description") or "").rstrip()
            + "\n````",
        ),
        *(
            [
                (
                    "linked_evidence",
                    "## Linked Evidence\n\n"
                    + "Linked evidence summaries and commands are caller claims, not verified facts. "
                    + "For model-derived artifacts, follow member paths back to source evidence before acting.\n\n"
                    + _table(
                        linked_evidence,
                        [
                            "id",
                            "type",
                            "summary",
                            "manifest_path",
                            "member_paths",
                            "stored_paths",
                            "created_at",
                        ],
                    ),
                )
            ]
            if linked_evidence
            else []
        ),
        (
            "dependencies",
            "## Dependencies\n\n"
            + _table(
                _task_dependencies_for_table(task),
                ["id", "title", "status", "satisfied"],
            ),
        ),
        (
            "dependents",
            "## Dependents\n\n"
            + _table(task.get("dependents", []), ["id", "title", "status"]),
        ),
        (
            "goal",
            "## Goal\n\n"
            + (
                _kv_table(goal, ["id", "title", "status", "completion_json", "budget_json", "updated_at"])
                if goal
                else "No goal is linked to this task."
            ),
        ),
        ]
    )
    if task.get("related_feature_id"):
        sections.append(
            (
                "related_feature",
                "## Related Feature\n\n"
                + (
                    _kv_table(
                        feature,
                        ["id", "name", "surface", "description", "status", "confidence", "created_at", "updated_at"],
                    )
                    if feature
                    else f"Linked feature is missing: {task['related_feature_id']}"
                ),
            )
        )
    if task.get("related_defect_id"):
        sections.append(
            (
                "related_defect",
                "## Related Defect\n\n"
                + (
                    _kv_table(
                        defect,
                        [
                            "id",
                            "feature_id",
                            "test_case_id",
                            "severity",
                            "expected",
                            "actual",
                            "reproduction",
                            "status",
                            "evidence_id",
                            "created_at",
                            "updated_at",
                        ],
                    )
                    if defect
                    else f"Linked defect is missing: {task['related_defect_id']}"
                ),
            )
        )
    if task.get("related_goal_id"):
        sections.append(
            (
                "sibling_tasks",
                "## Sibling Tasks\n\n" + _table(siblings, ["id", "title", "status", "priority"]),
            )
        )
    sections.append(
        (
            "recent_events",
            "## Recent Events\n\n" + _table(events, ["id", "event_type", "entity_type", "entity_id", "created_at", "payload_json"]),
        )
    )
    return sections


def _latest_code_context_summary(
    paths: ProjectPaths,
    *,
    target_type: str,
    target_id: str,
    now: str,
    require_bound_receipt: bool,
) -> dict[str, Any]:
    receipt_ref, selection_scope = _select_code_context_receipt_ref(
        paths,
        target_type=target_type,
        target_id=target_id,
        require_bound_receipt=require_bound_receipt,
    )
    if receipt_ref is None:
        return _stamp_code_context_pack_facts(
            _missing_code_context_summary(),
            target_type=target_type,
            target_id=target_id,
            now=now,
            selection_scope="missing_receipt",
        )

    receipt_path = resolve_context_receipt_path(paths, str(receipt_ref["receipt_path"]))
    try:
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        return _stamp_code_context_pack_facts(
            _unavailable_code_context_summary(
                receipt_ref=receipt_ref,
                message=f"Latest context receipt could not be loaded: {exc.__class__.__name__}.",
            ),
            target_type=target_type,
            target_id=target_id,
            now=now,
            selection_scope=selection_scope,
        )
    if not isinstance(receipt_payload, dict):
        return _stamp_code_context_pack_facts(
            _unavailable_code_context_summary(
                receipt_ref=receipt_ref,
                message="Latest context receipt is not a JSON object.",
            ),
            target_type=target_type,
            target_id=target_id,
            now=now,
            selection_scope=selection_scope,
        )

    summary = summarize_code_context_receipt(receipt_payload)
    summary_receipt_ref = summary.get("receipt_ref")
    created_at = (
        summary_receipt_ref.get("created_at")
        if isinstance(summary_receipt_ref, dict)
        else None
    )
    summary["receipt_ref"] = {
        **receipt_ref,
        "created_at": created_at or receipt_ref["created_at"],
    }
    return _stamp_code_context_pack_facts(
        summary,
        target_type=target_type,
        target_id=target_id,
        now=now,
        selection_scope=selection_scope,
    )


def _select_code_context_receipt_ref(
    paths: ProjectPaths,
    *,
    target_type: str,
    target_id: str,
    require_bound_receipt: bool,
) -> tuple[dict[str, str] | None, str]:
    conn = connect(paths.db_path)
    try:
        bound_evidence_id = newest_linked_evidence_id(
            conn,
            target_type=target_type,
            target_id=target_id,
            link_role=CODE_CONTEXT_LINK_ROLE,
        )
    finally:
        conn.close()
    selection_scope = "unscoped_latest"
    if bound_evidence_id:
        receipt_ref = evidence_ref_by_id(paths, bound_evidence_id)
        if receipt_ref is not None and receipt_ref.get("evidence_type") == CONTEXT_RECEIPT_EVIDENCE_TYPE:
            public_ref = _public_receipt_ref(receipt_ref)
            receipt_payload = _load_receipt_payload_for_binding_check(paths, public_ref)
            if receipt_payload is None:
                return public_ref, "target_bound"
            if _receipt_target_binding_agrees(
                receipt_payload,
                target_type=target_type,
                target_id=target_id,
            ):
                return public_ref, "target_bound"
            if require_bound_receipt:
                raise ContextPackBoundReceiptMismatchError(
                    target_type=target_type,
                    target_id=target_id,
                    evidence_id=str(public_ref["evidence_id"]),
                    claimed_target_binding=receipt_payload.get("target_binding"),
                    suggested_refresh_command=_target_refresh_command(target_type, target_id),
                )
            selection_scope = "unscoped_latest_after_bound_mismatch"
    if require_bound_receipt:
        raise ContextPackBoundReceiptRequiredError(
            target_type=target_type,
            target_id=target_id,
            suggested_refresh_command=_target_refresh_command(target_type, target_id),
        )
    receipt_ref = latest_context_receipt_ref(paths)
    if receipt_ref is None:
        return None, "missing_receipt"
    return receipt_ref, selection_scope


def _load_receipt_payload_for_binding_check(
    paths: ProjectPaths,
    receipt_ref: dict[str, str],
) -> dict[str, Any] | None:
    receipt_path = resolve_context_receipt_path(paths, str(receipt_ref["receipt_path"]))
    try:
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return None
    if not isinstance(receipt_payload, dict):
        return None
    return receipt_payload


def _public_receipt_ref(receipt_ref: dict[str, str]) -> dict[str, str]:
    return {
        "evidence_id": str(receipt_ref["evidence_id"]),
        "receipt_path": str(receipt_ref["receipt_path"]),
        "created_at": str(receipt_ref["created_at"]),
    }


def _stamp_code_context_pack_facts(
    summary: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    now: str,
    selection_scope: str,
) -> dict[str, Any]:
    stamped = summary_with_receipt_age(summary, now=now)
    stamped["relevance"] = _code_context_relevance(
        stamped,
        target_type=target_type,
        target_id=target_id,
        selection_scope=selection_scope,
    )
    if stamped.get("status") == "missing_receipt":
        stamped["next_actions"] = [
            "pcl index build --json",
            _target_refresh_command(target_type, target_id),
        ]
    replay = refresh_replay(stamped)
    stamped["refresh_replay"] = _target_refresh_replay(
        replay,
        target_type=target_type,
        target_id=target_id,
    )
    return stamped


def _code_context_relevance(
    summary: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    selection_scope: str,
) -> dict[str, str]:
    status = str(summary.get("status") or "")
    if status == "missing_receipt":
        return {
            "target_type": target_type,
            "target_id": target_id,
            "scope": "missing_receipt",
            "binding_strength": "none",
            "reason": "No context receipt was available for this pack target.",
        }
    if selection_scope == "target_bound":
        return {
            "target_type": target_type,
            "target_id": target_id,
            "scope": "target_bound",
            "binding_strength": "caller_asserted",
            "reason": (
                "A context receipt linked to this target was selected through evidence_links; "
                "the binding is a caller assertion, not semantic proof."
            ),
        }
    if selection_scope == "unscoped_latest_after_bound_mismatch":
        return {
            "target_type": target_type,
            "target_id": target_id,
            "scope": "unscoped_latest",
            "binding_strength": "none",
            "warning": (
                "A target-bound code context receipt link was skipped because the "
                "evidence link routing row and artifact binding disagree; using "
                "the latest context receipt by recency."
            ),
            "reason": (
                "The most recent context receipt was selected by recency; it was not "
                "accepted as target-bound for this target."
            ),
        }
    return {
        "target_type": target_type,
        "target_id": target_id,
        "scope": "unscoped_latest",
        "binding_strength": "none",
        "warning": "No target-bound code context receipt was found; using the latest unscoped receipt.",
        "reason": (
            "The most recent context receipt was selected by recency; it was not "
            "created for this target."
        ),
    }


def _target_refresh_command(target_type: str, target_id: str) -> str:
    if target_type == "agent_job":
        return f"pcl impact --diff --for-job {shlex.quote(target_id)} --json"
    return f"pcl impact --diff --for-task {shlex.quote(target_id)} --json"


def _target_refresh_replay(
    replay: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    payload = dict(replay if isinstance(replay, dict) else {})
    commands = payload.get("commands")
    if not isinstance(commands, list):
        return payload
    payload["commands"] = [
        _command_with_target(command, target_type=target_type, target_id=target_id)
        for command in commands
    ]
    return payload


def _command_with_target(command: Any, *, target_type: str, target_id: str) -> str:
    text = str(command)
    try:
        parts = shlex.split(text)
    except ValueError:
        return text
    if len(parts) < 3 or parts[:3] != ["pcl", "impact", "--diff"]:
        return text
    if "--for-task" in parts or "--for-job" in parts:
        return text
    flag = "--for-job" if target_type == "agent_job" else "--for-task"
    if "--json" in parts:
        index = parts.index("--json")
        parts[index:index] = [flag, target_id]
    else:
        parts.extend([flag, target_id])
    return " ".join(shlex.quote(part) for part in parts)


def _missing_code_context_summary() -> dict[str, Any]:
    return {
        "contract_version": CODE_CONTEXT_SUMMARY_VERSION,
        "status": "missing_receipt",
        "receipt_ref": {"evidence_id": None, "receipt_path": None, "created_at": None},
        "diff_source": "unknown",
        "index_run": None,
        "changed_file_count": 0,
        "excluded_changed_file_count": 0,
        "sensitive_omitted_count": 0,
        "staleness_warnings": [],
        "untracked_omission_warning": None,
        "included_total": 0,
        "included_candidate_context_top": [],
        "omitted_reason_counts": {},
        "verification_suggestions": [],
        "sensitive_include_override_used": False,
        "message": "No context receipt evidence was found.",
        "next_actions": [
            "pcl index build --json",
            "pcl impact --diff --json",
        ],
    }


def _unavailable_code_context_summary(
    *,
    receipt_ref: dict[str, str],
    message: str,
) -> dict[str, Any]:
    return {
        "contract_version": CODE_CONTEXT_SUMMARY_VERSION,
        "status": "receipt_unavailable",
        "receipt_ref": receipt_ref,
        "diff_source": "unknown",
        "index_run": None,
        "changed_file_count": 0,
        "excluded_changed_file_count": 0,
        "sensitive_omitted_count": 0,
        "staleness_warnings": [],
        "untracked_omission_warning": None,
        "included_total": 0,
        "included_candidate_context_top": [],
        "omitted_reason_counts": {},
        "verification_suggestions": [],
        "sensitive_include_override_used": False,
        "message": message,
        "next_actions": [
            "pcl index build --json",
            "pcl impact --diff --json",
        ],
    }


def _code_context_receipt_path(summary: dict[str, Any]) -> str | None:
    receipt_ref = summary.get("receipt_ref")
    if not isinstance(receipt_ref, dict):
        return None
    receipt_path = receipt_ref.get("receipt_path")
    if not receipt_path:
        return None
    return str(receipt_path)


def _code_context_sections(summary: dict[str, Any]) -> list[tuple[str, str]]:
    sections = [(CODE_CONTEXT_SAFETY_SECTION_ID, _render_code_context_safety_section(summary))]
    if summary.get("status") in {"missing_receipt", "receipt_unavailable"}:
        return sections
    sections.append(
        (
            CODE_CONTEXT_VERIFICATION_SECTION_ID,
            _render_code_context_verification_section(summary),
        )
    )
    sections.append((CODE_CONTEXT_DETAIL_SECTION_ID, _render_code_context_detail_section(summary)))
    return sections


def _render_code_context_safety_section(summary: dict[str, Any]) -> str:
    lines = ["## Code Context Safety", ""]
    status = str(summary.get("status") or "")
    if status == "missing_receipt":
        lines.extend(
            [
                "No context receipt evidence was found.",
                "",
                "Receipt selection and freshness facts:",
                *_render_code_context_selection_freshness_lines(summary),
                "",
                _render_code_context_next_action_line(summary),
            ]
        )
        return "\n".join(lines)
    if status == "receipt_unavailable":
        lines.extend(
            [
                str(summary.get("message") or "Latest context receipt is unavailable."),
                "",
                "Receipt selection and freshness facts:",
                *_render_code_context_selection_freshness_lines(summary),
                "",
                _render_code_context_next_action_line(summary),
            ]
        )
        return "\n".join(lines)

    receipt_ref = _format_receipt_ref(summary)
    staleness = summary.get("staleness_warnings")
    staleness_count = len(staleness) if isinstance(staleness, list) else 0
    untracked_warning = summary.get("untracked_omission_warning")
    untracked_value = "present" if untracked_warning else "none"
    lines.append(
        "Safety facts: "
        f"diff_source={_stringify(summary.get('diff_source'))}; "
        f"receipt_ref={receipt_ref}; "
        f"sensitive_omitted_count={_stringify(summary.get('sensitive_omitted_count'))}; "
        f"staleness_warnings={staleness_count}; "
        f"excluded_changed_file_count={_stringify(summary.get('excluded_changed_file_count'))}; "
        f"untracked_omission_warning={untracked_value}; "
        f"sensitive_include_override_used={_stringify(summary.get('sensitive_include_override_used'))}."
    )
    selection_freshness_lines = _render_code_context_selection_freshness_lines(summary)
    if selection_freshness_lines:
        lines.extend(["", "Receipt selection and freshness facts:"])
        lines.extend(selection_freshness_lines)
    if staleness_count:
        lines.extend(["", "Staleness warnings:"])
        for warning in staleness:
            lines.append(f"- {_stringify(warning)}")
    if untracked_warning:
        lines.extend(["", f"Untracked omission warning: {_stringify(untracked_warning)}"])
    return "\n".join(lines)


def _render_code_context_next_action_line(summary: dict[str, Any]) -> str:
    commands = recommended_refresh_commands(summary)
    if not commands:
        commands = ["pcl index build --json", "pcl impact --diff --json"]
    return "Next action: " + ", then ".join(f"`{command}`" for command in commands) + "."


def _render_code_context_selection_freshness_lines(summary: dict[str, Any]) -> list[str]:
    lines = []
    relevance = summary.get("relevance")
    if isinstance(relevance, dict):
        scope = _stringify(relevance.get("scope"))
        binding = _stringify(relevance.get("binding_strength"))
        reason = _short_relevance_reason(scope, _stringify(relevance.get("reason")))
        lines.append(f"- relevance: {scope} (binding: {binding}) - {reason}")
    lines.extend(render_receipt_age_lines(summary))
    return lines


def _short_relevance_reason(scope: str, fallback: str) -> str:
    if scope == "target_bound":
        return "target-bound receipt selected by caller assertion"
    if scope == "unscoped_latest":
        return "latest receipt, not created for this target"
    if scope == "missing_receipt":
        return "no receipt was available for this target"
    return fallback


def _render_code_context_verification_section(summary: dict[str, Any]) -> str:
    suggestions = summary.get("verification_suggestions")
    lines = ["## Code Context Verification Suggestions", ""]
    if isinstance(suggestions, list) and suggestions:
        for suggestion in suggestions:
            display = format_verification_suggestion_for_display(suggestion)
            if display:
                lines.append(f"- {display}")
    else:
        lines.append("None.")
    return "\n".join(lines)


def _render_code_context_detail_section(summary: dict[str, Any]) -> str:
    lines = [
        "## Code Context Detail",
        "",
        "Counts: "
        f"changed_file_count={_stringify(summary.get('changed_file_count'))}; "
        f"included_total={_stringify(summary.get('included_total'))}.",
    ]
    omitted_reason_counts = summary.get("omitted_reason_counts")
    if isinstance(omitted_reason_counts, dict) and omitted_reason_counts:
        lines.extend(["", "Omitted reason counts:"])
        for reason, count in omitted_reason_counts.items():
            lines.append(f"- {_stringify(reason)}: {_stringify(count)}")
    candidates = summary.get("included_candidate_context_top")
    if isinstance(candidates, list) and candidates:
        lines.extend(["", "Files included as candidate context:"])
        for item in candidates:
            if not isinstance(item, dict):
                continue
            path = _stringify(item.get("path"))
            role = _stringify(item.get("role"))
            reason = _stringify(item.get("reason"))
            lines.append(f"- {path} ({role}; {reason})")
    else:
        lines.extend(["", "Files included as candidate context: none."])
    return "\n".join(lines)


def _format_receipt_ref(summary: dict[str, Any]) -> str:
    receipt_ref = summary.get("receipt_ref")
    if not isinstance(receipt_ref, dict):
        return "none"
    evidence_id = receipt_ref.get("evidence_id")
    receipt_path = receipt_ref.get("receipt_path")
    if evidence_id and receipt_path:
        return str(evidence_id)
    if evidence_id:
        return str(evidence_id)
    if receipt_path:
        return str(receipt_path)
    return "none"


def _render_with_budget(
    *,
    title: str,
    sections: list[tuple[str, str]],
    max_tokens: int,
    section_priorities: dict[str, int],
) -> tuple[str, list[str], list[str], list[str]]:
    base = f"{title}\n\n"
    canonical_ids = [section_id for section_id, _ in sections]
    section_by_id = {section_id: section for section_id, section in sections}
    canonical_index = {section_id: index for index, section_id in enumerate(canonical_ids)}
    required_sections = _required_section_ids(canonical_ids)
    section_token_counts = {
        section_id: estimate_token_count(section_by_id[section_id].rstrip() + "\n\n")
        for section_id in canonical_ids
    }
    base_token_count = estimate_token_count(base)
    note_token_count = estimate_token_count(TRUNCATION_NOTE)
    required_token_count = base_token_count + sum(
        section_token_counts[section_id] for section_id in required_sections
    )

    if required_token_count > max_tokens:
        raise ContextPackBudgetError(
            details=_context_pack_budget_error_details(
                required_sections=required_sections,
                section_token_counts=section_token_counts,
                base_token_count=base_token_count,
                note_token_count=note_token_count,
                max_tokens=max_tokens,
            )
        )

    all_section_token_count = base_token_count + sum(section_token_counts.values())
    if all_section_token_count <= max_tokens:
        selected = set(canonical_ids)
        omitted: list[str] = []
        include_note = False
    else:
        if required_token_count + note_token_count > max_tokens:
            raise ContextPackBudgetError(
                details=_context_pack_budget_error_details(
                    required_sections=required_sections,
                    section_token_counts=section_token_counts,
                    base_token_count=base_token_count,
                    note_token_count=note_token_count,
                    max_tokens=max_tokens,
                )
            )

        selected = set(required_sections)
        selected_token_count = required_token_count + note_token_count
        optional_sections = [
            section_id
            for section_id in canonical_ids
            if section_id not in selected
        ]
        for section_id in sorted(
            optional_sections,
            key=lambda value: (-section_priorities.get(value, 0), canonical_index[value]),
        ):
            section_token_count = section_token_counts[section_id]
            if selected_token_count + section_token_count <= max_tokens:
                selected.add(section_id)
                selected_token_count += section_token_count
        omitted = [section_id for section_id in canonical_ids if section_id not in selected]
        include_note = bool(omitted)

    markdown = base
    included: list[str] = []
    for section_id, section in sections:
        if section_id not in selected:
            continue
        section_text = section.rstrip() + "\n\n"
        markdown += section_text
        included.append(section_id)
    if include_note:
        markdown += TRUNCATION_NOTE

    return markdown.rstrip() + "\n", included, omitted, required_sections


def _required_section_ids(canonical_ids: list[str]) -> list[str]:
    required = []
    if MACHINE_CONTEXT_RULES_SECTION_ID in canonical_ids:
        required.append(MACHINE_CONTEXT_RULES_SECTION_ID)
    if CODE_CONTEXT_SAFETY_SECTION_ID in canonical_ids:
        required.append(CODE_CONTEXT_SAFETY_SECTION_ID)
    return required


def _context_pack_budget_error_details(
    *,
    required_sections: list[str],
    section_token_counts: dict[str, int],
    base_token_count: int,
    note_token_count: int,
    max_tokens: int,
) -> dict[str, Any]:
    required_section_token_counts = {
        section_id: section_token_counts[section_id]
        for section_id in required_sections
    }
    return {
        "required_sections": required_sections,
        "required_section_token_counts": required_section_token_counts,
        "title_token_count": base_token_count,
        "truncation_note_token_count": note_token_count,
        "max_tokens": max_tokens,
        "estimated_min_max_tokens": (
            base_token_count
            + sum(required_section_token_counts.values())
            + note_token_count
        ),
    }


def _job_role_profile(role: str) -> tuple[str, dict[str, int]]:
    profile_name = role.strip().lower()
    if profile_name not in JOB_SECTION_PRIORITY_PROFILES:
        profile_name = "implementer"
    return profile_name, JOB_SECTION_PRIORITY_PROFILES[profile_name]


def _task_role_profile(role: str) -> tuple[str, dict[str, int]]:
    return "default", TASK_SECTION_PRIORITY_PROFILES["default"]


def _goal_for_task(conn, task: dict[str, Any]) -> dict[str, Any] | None:
    goal_id = task.get("related_goal_id")
    if not goal_id:
        return None
    return _one(
        conn,
        """
        SELECT id, title, status, completion_json, stop_conditions_json, budget_json, created_at, updated_at
        FROM goals
        WHERE id = ?
        """,
        (str(goal_id),),
    )


def _feature_for_task(conn, task: dict[str, Any]) -> dict[str, Any] | None:
    feature_id = task.get("related_feature_id")
    if not feature_id:
        return None
    return _one(
        conn,
        """
        SELECT id, name, surface, description, status, confidence, created_at, updated_at
        FROM features
        WHERE id = ?
        """,
        (str(feature_id),),
    )


def _defect_for_task(conn, task: dict[str, Any]) -> dict[str, Any] | None:
    defect_id = task.get("related_defect_id")
    if not defect_id:
        return None
    return _one(
        conn,
        """
        SELECT id, feature_id, test_case_id, severity, expected, actual, reproduction, status, evidence_id, created_at, updated_at
        FROM defects
        WHERE id = ?
        """,
        (str(defect_id),),
    )


def _sibling_tasks(conn, task: dict[str, Any]) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT id, title, status, priority
        FROM tasks
        WHERE related_goal_id = ?
          AND id != ?
          AND status NOT IN ('done', 'cancelled')
        ORDER BY priority, id
        """,
        (str(task["related_goal_id"]), str(task["id"])),
    )


def _linked_task_evidence(paths: ProjectPaths, conn, task_id: str) -> list[dict[str, Any]]:
    if table_exists(conn, "evidence_links"):
        rows = _rows(
            conn,
            """
            SELECT evidence.id, evidence.type, evidence.path, evidence.command,
                   evidence.summary, evidence.created_at
            FROM evidence_links
            JOIN evidence ON evidence.id = evidence_links.evidence_id
            WHERE evidence_links.target_type = 'task'
              AND evidence_links.target_id = ?
              AND evidence_links.link_role = 'supporting'
            ORDER BY evidence_links.created_at, evidence_links.evidence_id
            """,
            (task_id,),
        )
    elif not _table_has_column(conn, "evidence", "linked_task_id"):
        return []
    else:
        rows = _rows(
            conn,
            """
            SELECT id, type, path, command, summary, created_at
            FROM evidence
            WHERE linked_task_id = ?
            ORDER BY created_at, id
            """,
            (task_id,),
        )
    evidence: list[dict[str, Any]] = []
    for row in rows:
        manifest_path = str(row.get("path") or "")
        members = _adhoc_manifest_members(paths, manifest_path)
        member_paths = [str(member.get("path") or "") for member in members if member.get("path")]
        stored_paths = [
            str(member.get("stored_path") or "")
            for member in members
            if member.get("stored_path")
        ]
        evidence.append(
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "summary": row.get("summary"),
                "manifest_path": manifest_path,
                "member_paths": member_paths,
                "stored_paths": stored_paths,
                "created_at": row.get("created_at"),
            }
        )
    return evidence


def _table_has_column(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


def _adhoc_manifest_members(paths: ProjectPaths, manifest_path: str) -> list[dict[str, Any]]:
    absolute_path = _local_path(paths, manifest_path)
    if absolute_path is None or not absolute_path.is_file():
        return []
    try:
        payload = json.loads(absolute_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return []
    members = payload.get("members") if isinstance(payload, dict) else None
    if not isinstance(members, list):
        return []
    return [member for member in members if isinstance(member, dict)]


def _linked_task_evidence_source_paths(evidence: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        for value in [
            item.get("manifest_path"),
            *(item.get("stored_paths") or []),
            *(item.get("member_paths") or []),
        ]:
            path = str(value or "")
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _local_path(paths: ProjectPaths, path_value: str) -> Path | None:
    if "://" in path_value or path_value.startswith("inline:"):
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = paths.root / path
    return path


def _task_dependencies_for_table(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dependency in task.get("dependencies", []):
        row = dict(dependency)
        row["satisfied"] = "yes" if row.get("status") in COMPLETED_DEPENDENCY_STATUSES else "no"
        rows.append(row)
    return rows


def _add_verification_rubric_columns(verifications: list[dict[str, Any]]) -> None:
    for verification in verifications:
        verification["confidence_score"] = ""
        verification["evidence_completeness"] = ""
        rubric = _json_object(verification.get("rubric_json"))
        if claims_rubric_v1(rubric):
            verification["confidence_score"] = rubric.get("confidence_score", "")
            verification["evidence_completeness"] = rubric.get("evidence_completeness", "")


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


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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
