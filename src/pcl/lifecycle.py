from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .db import connect
from .evidence import record_inline_evidence
from .errors import EXIT_USAGE, InvalidInputError, PclError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .rubric import (
    claims_rubric_v1,
    evidence_ids_in_rubric,
    rubric_contract_version,
    validate_rubric,
)
from .timeutil import utc_now_iso


ACTIVE_JOB_STATUSES = {"queued", "running", "blocked"}
TERMINAL_JOB_STATUSES = {"passed", "failed", "cancelled"}
ACTIVE_RUN_STATUSES = {"queued", "running", "blocked"}
ACTIVE_DEFECT_STATUSES = {"open", "triaged", "in_progress", "fixed", "verified"}


class JobCompletionEvidenceError(PclError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any]) -> None:
        super().__init__(
            message=message,
            code=code,
            exit_code=EXIT_USAGE,
            details=details,
        )


def complete_job(
    paths: ProjectPaths,
    *,
    job_id: str,
    summary: str,
    output_path: str | None = None,
    evidence_id: str | None = None,
    token_input: int | None = None,
    token_output: int | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    _require_summary(summary)
    normalized_output = _normalize_output_path(paths, output_path)
    normalized_evidence_id = _normalize_evidence_id(evidence_id)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        _require_active_status("Agent job", job_id, str(job["status"]), ACTIVE_JOB_STATUSES)
        if normalized_evidence_id is not None:
            _require_evidence_exists(conn, normalized_evidence_id)
        run_started = _run_started_update(conn, paths, str(job["workflow_run_id"]), now)
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?, output_path = COALESCE(?, output_path), token_input = COALESCE(?, token_input),
                token_output = COALESCE(?, token_output), started_at = COALESCE(started_at, ?),
                ended_at = ?, summary = ?, lease_expires_at = NULL, last_heartbeat_at = NULL
            WHERE id = ?
            """,
            ("passed", normalized_output, token_input, token_output, now, now, summary, job_id),
        )
        event_payload = {
            "workflow_run_id": job["workflow_run_id"],
            "summary": summary,
            "output_path": normalized_output,
            "token_input": token_input,
            "token_output": token_output,
        }
        if normalized_evidence_id is not None:
            event_payload["evidence_id"] = normalized_evidence_id
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_job_completed",
            entity_type="agent_job",
            entity_id=job_id,
            payload=event_payload,
        )
        conn.commit()
        result = {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": job["workflow_run_id"],
            "status": "passed",
            "summary": summary,
            "output_path": normalized_output,
            "workflow_started": run_started,
        }
        if normalized_evidence_id is not None:
            result["evidence_id"] = normalized_evidence_id
            result["latest_evidence_id"] = normalized_evidence_id
        return result
    finally:
        conn.close()


def fail_job(paths: ProjectPaths, *, job_id: str, summary: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        _require_active_status("Agent job", job_id, str(job["status"]), ACTIVE_JOB_STATUSES)
        workflow_run_id = str(job["workflow_run_id"])
        _require_active_status(
            "Workflow run",
            workflow_run_id,
            str(_get_run(conn, workflow_run_id)["status"]),
            ACTIVE_RUN_STATUSES,
        )
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?,
                started_at = COALESCE(started_at, ?),
                ended_at = ?,
                summary = ?,
                lease_expires_at = NULL,
                last_heartbeat_at = NULL
            WHERE id = ?
            """,
            ("failed", now, now, summary, job_id),
        )
        cancelled_jobs = _cancel_active_jobs_for_failed_run(
            conn,
            paths,
            workflow_run_id=workflow_run_id,
            summary=summary,
            now=now,
            exclude_job_id=job_id,
            failed_job_id=job_id,
        )
        conn.execute(
            "UPDATE workflow_runs SET status = ?, ended_at = ?, summary = ? WHERE id = ?",
            ("failed", now, summary, workflow_run_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_job_failed",
            entity_type="agent_job",
            entity_id=job_id,
            payload={"workflow_run_id": workflow_run_id, "summary": summary},
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_run_failed",
            entity_type="workflow_run",
            entity_id=workflow_run_id,
            payload={"failed_job_id": job_id, "summary": summary, "cancelled_jobs": cancelled_jobs},
        )
        conn.commit()
        return {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": workflow_run_id,
            "status": "failed",
            "summary": summary,
            "cancelled_jobs": cancelled_jobs,
        }
    finally:
        conn.close()


def cancel_job(paths: ProjectPaths, *, job_id: str, summary: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(job_id, "job_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        job = _get_job(conn, job_id)
        _require_active_status("Agent job", job_id, str(job["status"]), ACTIVE_JOB_STATUSES)
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?, ended_at = ?, summary = ?, lease_expires_at = NULL, last_heartbeat_at = NULL
            WHERE id = ?
            """,
            ("cancelled", now, summary, job_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_job_cancelled",
            entity_type="agent_job",
            entity_id=job_id,
            payload={"workflow_run_id": job["workflow_run_id"], "summary": summary},
        )
        conn.commit()
        return {
            "ok": True,
            "job_id": job_id,
            "workflow_run_id": job["workflow_run_id"],
            "status": "cancelled",
            "summary": summary,
        }
    finally:
        conn.close()


def record_verification(
    paths: ProjectPaths,
    *,
    workflow_run_id: str,
    result: str,
    reasons: list[str],
    verifier_role: str = "human",
    rubric_json: str = "{}",
    target_job_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(workflow_run_id, "workflow_run_id")
    if target_job_id:
        _validate_identifier(target_job_id, "target_job_id")
    if result not in {"approved", "rejected", "needs_human", "inconclusive"}:
        raise InvalidInputError(
            f"Invalid verification result: {result}",
            details={"result": result},
        )
    if not reasons or not any(reason.strip() for reason in reasons):
        raise InvalidInputError("At least one --reason is required to record verification.")
    rubric_obj = _json_object_from_raw(rubric_json, "rubric-json")
    rubric_contract = rubric_contract_version(rubric_obj)
    if claims_rubric_v1(rubric_obj):
        rubric_errors = validate_rubric(rubric_obj)
        if rubric_errors:
            raise InvalidInputError(
                "rubric-json does not satisfy rubric/v1.",
                details={"errors": rubric_errors},
            )
    rubric = json.dumps(rubric_obj, ensure_ascii=False, sort_keys=True)
    cleaned_reasons = [reason.strip() for reason in reasons if reason.strip()]
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        run = _get_run(conn, workflow_run_id)
        if target_job_id:
            job = _get_job(conn, target_job_id)
            if job["workflow_run_id"] != workflow_run_id:
                raise InvalidInputError(
                    f"Agent job {target_job_id} does not belong to workflow run {workflow_run_id}.",
                    details={"job_id": target_job_id, "workflow_run_id": workflow_run_id},
                )
        evidence_ids = evidence_ids_in_rubric(rubric_obj) if claims_rubric_v1(rubric_obj) else []
        missing_evidence_ids = _missing_evidence_ids(conn, evidence_ids)
        if missing_evidence_ids:
            raise InvalidInputError(
                "rubric-json references missing evidence.",
                details={"missing_evidence_ids": missing_evidence_ids},
            )
        verification_id = next_prefixed_id(conn, "verifications", "V")
        reasons_json = json.dumps(cleaned_reasons, ensure_ascii=False, sort_keys=True)
        conn.execute(
            """
            INSERT INTO verifications(id, workflow_run_id, target_job_id, verifier_role, rubric_json, result, reasons_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (verification_id, workflow_run_id, target_job_id, verifier_role, rubric, result, reasons_json, now),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="verification_recorded",
            entity_type="verification",
            entity_id=verification_id,
            payload={
                "workflow_run_id": workflow_run_id,
                "workflow_id": run["workflow_id"],
                "target_job_id": target_job_id,
                "verifier_role": verifier_role,
                "result": result,
                "reasons": cleaned_reasons,
                "rubric_contract_version": rubric_contract,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "id": verification_id,
            "workflow_run_id": workflow_run_id,
            "target_job_id": target_job_id,
            "result": result,
            "reasons": cleaned_reasons,
            "rubric_contract_version": rubric_contract,
        }
    finally:
        conn.close()


def complete_workflow_run(paths: ProjectPaths, *, workflow_run_id: str, summary: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(workflow_run_id, "workflow_run_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        run = _get_run(conn, workflow_run_id)
        _require_active_status("Workflow run", workflow_run_id, str(run["status"]), ACTIVE_RUN_STATUSES)
        job_statuses = _job_status_counts(conn, workflow_run_id)
        not_passed = {status: count for status, count in job_statuses.items() if status != "passed" and count}
        if not_passed:
            raise InvalidInputError(
                f"Workflow run {workflow_run_id} cannot be completed until every job has passed.",
                details={"workflow_run_id": workflow_run_id, "job_statuses": job_statuses},
            )
        verification_id = _approved_verification_id(conn, workflow_run_id)
        if verification_id is None:
            raise InvalidInputError(
                f"Workflow run {workflow_run_id} requires an approved verification before completion.",
                details={"workflow_run_id": workflow_run_id},
            )
        conn.execute(
            "UPDATE workflow_runs SET status = ?, ended_at = ?, summary = ? WHERE id = ?",
            ("passed", now, summary, workflow_run_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_run_completed",
            entity_type="workflow_run",
            entity_id=workflow_run_id,
            payload={"summary": summary, "verification_id": verification_id},
        )
        conn.commit()
        return {
            "ok": True,
            "workflow_run_id": workflow_run_id,
            "status": "passed",
            "summary": summary,
            "verification_id": verification_id,
        }
    finally:
        conn.close()


def fail_workflow_run(paths: ProjectPaths, *, workflow_run_id: str, summary: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(workflow_run_id, "workflow_run_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        run = _get_run(conn, workflow_run_id)
        _require_active_status("Workflow run", workflow_run_id, str(run["status"]), ACTIVE_RUN_STATUSES)
        cancelled_jobs = _cancel_active_jobs_for_failed_run(
            conn,
            paths,
            workflow_run_id=workflow_run_id,
            summary=summary,
            now=now,
        )
        conn.execute(
            "UPDATE workflow_runs SET status = ?, ended_at = ?, summary = ? WHERE id = ?",
            ("failed", now, summary, workflow_run_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_run_failed",
            entity_type="workflow_run",
            entity_id=workflow_run_id,
            payload={"summary": summary, "cancelled_jobs": cancelled_jobs},
        )
        conn.commit()
        return {
            "ok": True,
            "workflow_run_id": workflow_run_id,
            "status": "failed",
            "summary": summary,
            "cancelled_jobs": cancelled_jobs,
        }
    finally:
        conn.close()


def cancel_workflow_run(paths: ProjectPaths, *, workflow_run_id: str, summary: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(workflow_run_id, "workflow_run_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        run = _get_run(conn, workflow_run_id)
        _require_active_status("Workflow run", workflow_run_id, str(run["status"]), ACTIVE_RUN_STATUSES)
        active_jobs = conn.execute(
            "SELECT id, status FROM agent_jobs WHERE workflow_run_id = ? AND status IN ('queued', 'running', 'blocked') ORDER BY id",
            (workflow_run_id,),
        ).fetchall()
        cancelled_jobs: list[str] = []
        for job in active_jobs:
            conn.execute(
                """
                UPDATE agent_jobs
                SET status = ?, ended_at = ?, summary = ?, lease_expires_at = NULL, last_heartbeat_at = NULL
                WHERE id = ?
                """,
                ("cancelled", now, summary, job["id"]),
            )
            cancelled_jobs.append(str(job["id"]))
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="agent_job_cancelled",
                entity_type="agent_job",
                entity_id=str(job["id"]),
                payload={"workflow_run_id": workflow_run_id, "summary": summary, "cancelled_with_run": True},
            )
        conn.execute(
            "UPDATE workflow_runs SET status = ?, ended_at = ?, summary = ? WHERE id = ?",
            ("cancelled", now, summary, workflow_run_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_run_cancelled",
            entity_type="workflow_run",
            entity_id=workflow_run_id,
            payload={"summary": summary, "cancelled_jobs": cancelled_jobs},
        )
        conn.commit()
        return {
            "ok": True,
            "workflow_run_id": workflow_run_id,
            "status": "cancelled",
            "summary": summary,
            "cancelled_jobs": cancelled_jobs,
        }
    finally:
        conn.close()


def close_goal(
    paths: ProjectPaths,
    *,
    goal_id: str,
    summary: str,
    evidence: str = "",
    verification_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(goal_id, "goal_id")
    if verification_id:
        _validate_identifier(verification_id, "verification_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        goal = _get_goal(conn, goal_id)
        goal_status = str(goal["status"])
        if goal_status == "closed":
            return {
                "ok": True,
                "goal_id": goal_id,
                "status": goal_status,
                "changed": False,
                "evidence_recorded": False,
            }
        _require_goal_open(goal)
        if not evidence.strip() and not verification_id:
            raise InvalidInputError("Closing a goal requires --evidence or --verification.")
        active_runs = _active_runs_for_goal(conn, goal_id)
        if active_runs:
            raise InvalidInputError(
                f"Goal {goal_id} cannot be closed while workflow runs are active.",
                details={"goal_id": goal_id, "active_workflow_runs": active_runs},
            )
        if verification_id:
            _require_approved_goal_verification(conn, goal_id, verification_id)
        completion = _completion_with_closure(
            str(goal["completion_json"]),
            summary=summary,
            evidence=evidence,
            verification_id=verification_id,
        )
        conn.execute(
            "UPDATE goals SET status = ?, completion_json = ?, updated_at = ? WHERE id = ?",
            ("closed", completion, now, goal_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="goal_closed",
            entity_type="goal",
            entity_id=goal_id,
            payload={"summary": summary, "evidence": evidence, "verification_id": verification_id},
        )
        conn.commit()
        return {
            "ok": True,
            "goal_id": goal_id,
            "status": "closed",
            "summary": summary,
            "evidence": evidence,
            "verification_id": verification_id,
            "changed": True,
        }
    finally:
        conn.close()


def cancel_goal(paths: ProjectPaths, *, goal_id: str, summary: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(goal_id, "goal_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        goal = _get_goal(conn, goal_id)
        goal_status = str(goal["status"])
        if goal_status == "cancelled":
            return {
                "ok": True,
                "goal_id": goal_id,
                "status": goal_status,
                "changed": False,
                "evidence_recorded": False,
            }
        _require_goal_open(goal)
        active_runs = _active_runs_for_goal(conn, goal_id)
        if active_runs:
            raise InvalidInputError(
                f"Goal {goal_id} cannot be cancelled while workflow runs are active.",
                details={"goal_id": goal_id, "active_workflow_runs": active_runs},
            )
        conn.execute(
            "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?",
            ("cancelled", now, goal_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="goal_cancelled",
            entity_type="goal",
            entity_id=goal_id,
            payload={"summary": summary},
        )
        conn.commit()
        return {"ok": True, "goal_id": goal_id, "status": "cancelled", "summary": summary, "changed": True}
    finally:
        conn.close()


def triage_defect(paths: ProjectPaths, *, defect_id: str, summary: str) -> dict[str, Any]:
    return _transition_defect(
        paths,
        defect_id=defect_id,
        new_status="triaged",
        event_type="defect_triaged",
        summary=summary,
        allowed_statuses={"open"},
    )


def start_defect(paths: ProjectPaths, *, defect_id: str, summary: str) -> dict[str, Any]:
    return _transition_defect(
        paths,
        defect_id=defect_id,
        new_status="in_progress",
        event_type="defect_started",
        summary=summary,
        allowed_statuses={"triaged"},
    )


def fix_defect(paths: ProjectPaths, *, defect_id: str, summary: str, evidence: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(defect_id, "defect_id")
    _require_summary(summary)
    _require_text(evidence, "--evidence is required to mark a defect fixed.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        defect = _get_defect(conn, defect_id)
        _require_active_status("Defect", defect_id, str(defect["status"]), {"in_progress"})
        evidence_id = record_inline_evidence(
            conn,
            evidence_type="defect_fix",
            summary=evidence.strip(),
            context=f"defect/{defect_id}/fix",
            command="pcl defect fix",
        )
        conn.execute(
            "UPDATE defects SET status = ?, evidence_id = ?, updated_at = ? WHERE id = ?",
            ("fixed", evidence_id, now, defect_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="defect_fixed",
            entity_type="defect",
            entity_id=defect_id,
            payload={"summary": summary, "evidence": evidence.strip(), "evidence_id": evidence_id},
        )
        conn.commit()
        return {
            "ok": True,
            "defect_id": defect_id,
            "status": "fixed",
            "summary": summary,
            "evidence_id": evidence_id,
        }
    finally:
        conn.close()


def verify_defect(
    paths: ProjectPaths,
    *,
    defect_id: str,
    summary: str,
    verification_id: str,
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(defect_id, "defect_id")
    _validate_identifier(verification_id, "verification_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        defect = _get_defect(conn, defect_id)
        _require_active_status("Defect", defect_id, str(defect["status"]), {"fixed"})
        verification = _require_approved_defect_verification(conn, defect_id, verification_id)
        conn.execute(
            "UPDATE defects SET status = ?, updated_at = ? WHERE id = ?",
            ("verified", now, defect_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="defect_verified",
            entity_type="defect",
            entity_id=defect_id,
            payload={
                "summary": summary,
                "verification_id": verification_id,
                "workflow_run_id": verification["workflow_run_id"],
            },
        )
        conn.commit()
        return {
            "ok": True,
            "defect_id": defect_id,
            "status": "verified",
            "summary": summary,
            "verification_id": verification_id,
            "workflow_run_id": verification["workflow_run_id"],
        }
    finally:
        conn.close()


def close_defect(paths: ProjectPaths, *, defect_id: str, summary: str, evidence: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(defect_id, "defect_id")
    _require_summary(summary)
    _require_text(evidence, "--evidence is required to close a defect.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        defect = _get_defect(conn, defect_id)
        _require_active_status("Defect", defect_id, str(defect["status"]), {"verified"})
        evidence_id = record_inline_evidence(
            conn,
            evidence_type="defect_close",
            summary=evidence.strip(),
            context=f"defect/{defect_id}/close",
            command="pcl defect close",
        )
        conn.execute(
            "UPDATE defects SET status = ?, evidence_id = ?, updated_at = ? WHERE id = ?",
            ("closed", evidence_id, now, defect_id),
        )
        feature_status = _refresh_feature_status_for_defect(conn, paths, str(defect["feature_id"]), now)
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="defect_closed",
            entity_type="defect",
            entity_id=defect_id,
            payload={
                "summary": summary,
                "evidence": evidence.strip(),
                "evidence_id": evidence_id,
                "feature_id": defect["feature_id"],
                "feature_status": feature_status,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "defect_id": defect_id,
            "status": "closed",
            "summary": summary,
            "evidence_id": evidence_id,
            "feature_id": defect["feature_id"],
            "feature_status": feature_status,
        }
    finally:
        conn.close()


def waive_defect(paths: ProjectPaths, *, defect_id: str, reason: str) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(defect_id, "defect_id")
    _require_text(reason, "--reason is required to waive a defect.")
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        defect = _get_defect(conn, defect_id)
        _require_active_status("Defect", defect_id, str(defect["status"]), ACTIVE_DEFECT_STATUSES)
        evidence_id = record_inline_evidence(
            conn,
            evidence_type="defect_waiver",
            summary=reason.strip(),
            context=f"defect/{defect_id}/waive",
            command="pcl defect waive",
        )
        conn.execute(
            "UPDATE defects SET status = ?, evidence_id = ?, updated_at = ? WHERE id = ?",
            ("waived", evidence_id, now, defect_id),
        )
        feature_status = _refresh_feature_status_for_defect(conn, paths, str(defect["feature_id"]), now)
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="defect_waived",
            entity_type="defect",
            entity_id=defect_id,
            payload={
                "reason": reason.strip(),
                "evidence_id": evidence_id,
                "feature_id": defect["feature_id"],
                "feature_status": feature_status,
            },
        )
        conn.commit()
        return {
            "ok": True,
            "defect_id": defect_id,
            "status": "waived",
            "reason": reason.strip(),
            "evidence_id": evidence_id,
            "feature_id": defect["feature_id"],
            "feature_status": feature_status,
        }
    finally:
        conn.close()


def _transition_defect(
    paths: ProjectPaths,
    *,
    defect_id: str,
    new_status: str,
    event_type: str,
    summary: str,
    allowed_statuses: set[str],
) -> dict[str, Any]:
    require_initialized(paths)
    _validate_identifier(defect_id, "defect_id")
    _require_summary(summary)
    now = utc_now_iso()

    conn = connect(paths.db_path)
    try:
        defect = _get_defect(conn, defect_id)
        _require_active_status("Defect", defect_id, str(defect["status"]), allowed_statuses)
        conn.execute(
            "UPDATE defects SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, defect_id),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="defect",
            entity_id=defect_id,
            payload={"summary": summary, "previous_status": defect["status"], "status": new_status},
        )
        conn.commit()
        return {"ok": True, "defect_id": defect_id, "status": new_status, "summary": summary}
    finally:
        conn.close()


def _get_job(conn, job_id: str):
    row = conn.execute(
        "SELECT id, workflow_run_id, status FROM agent_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Agent job does not exist: {job_id}", details={"job_id": job_id})
    return row


def _get_run(conn, workflow_run_id: str):
    row = conn.execute(
        "SELECT id, workflow_id, goal_id, status FROM workflow_runs WHERE id = ?",
        (workflow_run_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Workflow run does not exist: {workflow_run_id}",
            details={"workflow_run_id": workflow_run_id},
        )
    return row


def _get_goal(conn, goal_id: str):
    row = conn.execute("SELECT id, status, completion_json FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if row is None:
        raise InvalidInputError(f"Goal does not exist: {goal_id}", details={"goal_id": goal_id})
    return row


def _get_defect(conn, defect_id: str):
    row = conn.execute(
        "SELECT id, feature_id, status, evidence_id FROM defects WHERE id = ?",
        (defect_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(f"Defect does not exist: {defect_id}", details={"defect_id": defect_id})
    return row


def _cancel_active_jobs_for_failed_run(
    conn,
    paths: ProjectPaths,
    *,
    workflow_run_id: str,
    summary: str,
    now: str,
    exclude_job_id: str | None = None,
    failed_job_id: str | None = None,
) -> list[str]:
    params: list[str] = [workflow_run_id]
    excluded = ""
    if exclude_job_id:
        excluded = "AND id != ?"
        params.append(exclude_job_id)
    active_jobs = conn.execute(
        f"""
        SELECT id FROM agent_jobs
        WHERE workflow_run_id = ?
          AND status IN ('queued', 'running', 'blocked')
          {excluded}
        ORDER BY id
        """,
        params,
    ).fetchall()
    cancelled_jobs: list[str] = []
    for job in active_jobs:
        cancelled_job_id = str(job["id"])
        conn.execute(
            """
            UPDATE agent_jobs
            SET status = ?, ended_at = ?, summary = ?, lease_expires_at = NULL, last_heartbeat_at = NULL
            WHERE id = ?
            """,
            ("cancelled", now, summary, cancelled_job_id),
        )
        cancelled_jobs.append(cancelled_job_id)
        payload: dict[str, Any] = {
            "workflow_run_id": workflow_run_id,
            "summary": summary,
            "cancelled_with_run_failure": True,
        }
        if failed_job_id:
            payload["failed_job_id"] = failed_job_id
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="agent_job_cancelled",
            entity_type="agent_job",
            entity_id=cancelled_job_id,
            payload=payload,
        )
    return cancelled_jobs


def _run_started_update(conn, paths: ProjectPaths, workflow_run_id: str, now: str) -> bool:
    run = _get_run(conn, workflow_run_id)
    if run["status"] != "queued":
        return False
    conn.execute("UPDATE workflow_runs SET status = ? WHERE id = ?", ("running", workflow_run_id))
    append_event(
        conn=conn,
        events_path=paths.events_path,
        event_type="workflow_run_started",
        entity_type="workflow_run",
        entity_id=workflow_run_id,
        payload={"started_at": now},
    )
    return True


def _job_status_counts(conn, workflow_run_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM agent_jobs WHERE workflow_run_id = ? GROUP BY status",
        (workflow_run_id,),
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _approved_verification_id(conn, workflow_run_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT id FROM verifications
        WHERE workflow_run_id = ? AND result = 'approved'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (workflow_run_id,),
    ).fetchone()
    return None if row is None else str(row["id"])


def _require_approved_goal_verification(conn, goal_id: str, verification_id: str) -> None:
    row = conn.execute(
        """
        SELECT verifications.id, verifications.result, workflow_runs.goal_id
        FROM verifications
        JOIN workflow_runs ON workflow_runs.id = verifications.workflow_run_id
        WHERE verifications.id = ?
        """,
        (verification_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Verification does not exist: {verification_id}",
            details={"verification_id": verification_id},
        )
    if row["result"] != "approved":
        raise InvalidInputError(
            f"Verification {verification_id} is not approved.",
            details={"verification_id": verification_id, "result": row["result"]},
        )
    if row["goal_id"] != goal_id:
        raise InvalidInputError(
            f"Verification {verification_id} does not belong to goal {goal_id}.",
            details={"verification_id": verification_id, "goal_id": goal_id},
        )


def _require_approved_defect_verification(conn, defect_id: str, verification_id: str):
    row = conn.execute(
        """
        SELECT verifications.id, verifications.result, workflow_runs.id AS workflow_run_id, workflow_runs.summary
        FROM verifications
        JOIN workflow_runs ON workflow_runs.id = verifications.workflow_run_id
        WHERE verifications.id = ?
        """,
        (verification_id,),
    ).fetchone()
    if row is None:
        raise InvalidInputError(
            f"Verification does not exist: {verification_id}",
            details={"verification_id": verification_id},
        )
    if row["result"] != "approved":
        raise InvalidInputError(
            f"Verification {verification_id} is not approved.",
            details={"verification_id": verification_id, "result": row["result"]},
        )
    summary = str(row["summary"] or "")
    if f"defect={defect_id}" not in summary.split() and not _workflow_run_created_for_defect(
        conn,
        workflow_run_id=str(row["workflow_run_id"]),
        defect_id=defect_id,
    ):
        raise InvalidInputError(
            f"Verification {verification_id} is not tied to defect {defect_id}.",
            details={
                "verification_id": verification_id,
                "defect_id": defect_id,
                "workflow_run_id": row["workflow_run_id"],
            },
        )
    return row


def _workflow_run_created_for_defect(conn, *, workflow_run_id: str, defect_id: str) -> bool:
    rows = conn.execute(
        """
        SELECT payload_json FROM events
        WHERE entity_type = 'workflow_run'
          AND entity_id = ?
          AND event_type = 'workflow_run_created'
        ORDER BY created_at DESC
        """,
        (workflow_run_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except JSONDecodeError:
            continue
        if payload.get("defect_id") == defect_id:
            return True
    return False


def _active_runs_for_goal(conn, goal_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM workflow_runs WHERE goal_id = ? AND status IN ('queued', 'running', 'blocked') ORDER BY id",
        (goal_id,),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def _refresh_feature_status_for_defect(conn, paths: ProjectPaths, feature_id: str, now: str) -> str:
    feature = conn.execute("SELECT id, status FROM features WHERE id = ?", (feature_id,)).fetchone()
    if feature is None:
        return ""
    active_count = conn.execute(
        "SELECT COUNT(*) AS count FROM defects WHERE feature_id = ? AND status NOT IN ('closed', 'waived')",
        (feature_id,),
    ).fetchone()["count"]
    if active_count:
        next_status = "needs_fix"
    else:
        closed_count = conn.execute(
            "SELECT COUNT(*) AS count FROM defects WHERE feature_id = ? AND status = 'closed'",
            (feature_id,),
        ).fetchone()["count"]
        next_status = "passing" if closed_count else "waived"
    if feature["status"] != next_status:
        conn.execute("UPDATE features SET status = ?, updated_at = ? WHERE id = ?", (next_status, now, feature_id))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="feature_status_updated",
            entity_type="feature",
            entity_id=feature_id,
            payload={"previous_status": feature["status"], "status": next_status, "reason": "defect_lifecycle"},
        )
    return next_status


def _completion_with_closure(
    raw_completion_json: str,
    *,
    summary: str,
    evidence: str,
    verification_id: str | None,
) -> str:
    try:
        value = json.loads(raw_completion_json or "{}")
    except JSONDecodeError:
        value = {}
    if not isinstance(value, dict):
        value = {}
    value["closure"] = {
        "summary": summary,
        "evidence": evidence,
        "verification_id": verification_id,
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalized_json_object(raw: str, field_name: str) -> str:
    value = _json_object_from_raw(raw, field_name)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object_from_raw(raw: str, field_name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except JSONDecodeError as exc:
        raise InvalidInputError(
            f"{field_name} must be valid JSON: {exc.msg}.",
            details={"field": field_name, "position": exc.pos},
        ) from exc
    if not isinstance(value, dict):
        raise InvalidInputError(
            f"{field_name} must be a JSON object.",
            details={"field": field_name, "type": type(value).__name__},
        )
    return value


def _missing_evidence_ids(conn, evidence_ids: list[str]) -> list[str]:
    if not evidence_ids:
        return []
    placeholders = ", ".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"SELECT id FROM evidence WHERE id IN ({placeholders})",
        tuple(evidence_ids),
    ).fetchall()
    found = {str(row["id"]) for row in rows}
    return sorted(evidence_id for evidence_id in evidence_ids if evidence_id not in found)


def _normalize_evidence_id(evidence_id: str | None) -> str | None:
    if evidence_id is None:
        return None
    normalized = evidence_id.strip()
    if not normalized:
        raise JobCompletionEvidenceError(
            "--evidence must not be empty.",
            code="job_completion_empty_evidence",
            details={"field": "evidence"},
        )
    _validate_identifier(normalized, "evidence")
    return normalized


def _require_evidence_exists(conn, evidence_id: str) -> None:
    row = conn.execute("SELECT id FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    if row is None:
        raise JobCompletionEvidenceError(
            f"Evidence does not exist: {evidence_id}.",
            code="job_completion_missing_evidence",
            details={"evidence_id": evidence_id},
        )


def _normalize_output_path(paths: ProjectPaths, output_path: str | None) -> str | None:
    if output_path is None or output_path == "":
        return None
    path = Path(output_path)
    if not path.is_absolute():
        path = paths.root / path
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(paths.root)
    except ValueError as exc:
        raise InvalidInputError(
            "Job output path must be inside the project root.",
            details={"output_path": output_path, "root": str(paths.root)},
        ) from exc
    if not resolved.exists() or not resolved.is_file():
        raise InvalidInputError(
            f"Job output file does not exist: {output_path}",
            details={"output_path": output_path},
        )
    return str(relative)


def _require_active_status(entity: str, entity_id: str, status: str, allowed: set[str]) -> None:
    if status not in allowed:
        raise InvalidInputError(
            f"{entity} {entity_id} cannot transition from status {status}.",
            details={"id": entity_id, "status": status, "allowed": sorted(allowed)},
        )


def _require_goal_open(goal) -> None:
    if goal["status"] in {"closed", "cancelled"}:
        raise InvalidInputError(
            f"Goal {goal['id']} is already {goal['status']}.",
            details={"goal_id": goal["id"], "status": goal["status"]},
        )


def _require_summary(summary: str) -> None:
    if not summary.strip():
        raise InvalidInputError("--summary is required for lifecycle transitions.")


def _require_text(value: str, message: str) -> None:
    if not value.strip():
        raise InvalidInputError(message)


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(c.isalnum() or c in {"_", "-"} for c in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={"field": field_name, "value": value},
        )
