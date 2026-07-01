from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .agents import generate_agent_command
from .db import connect
from .errors import InvalidInputError
from .events import append_event
from .guards import require_initialized
from .ids import next_prefixed_id
from .lifecycle import (
    ACTIVE_RUN_STATUSES,
    close_goal,
    complete_workflow_run,
    fail_job,
    fail_workflow_run,
    record_verification,
)
from .paths import ProjectPaths
from .renderer import render_dashboard
from .timeutil import utc_now_iso
from .validators import validate_project
from .workflow_sandbox import execute_planned_sandbox_command, plan_workflow_template_sandbox
from .workflow_verifier import verify_workflow_template
from .workflows import WorkflowTemplate, load_workflow_template, read_job, run_workflow


CONTRACT_VERSION = "workflow-executor/v1"
EXECUTABLE_AGENT_ADAPTERS = {"generic_shell", "codex_exec"}
RETRYABLE_RUN_STATUSES = {"failed", "cancelled"}


def execute_workflow(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    goal_id: str | None = None,
    defect_id: str | None = None,
    agent_adapter: str = "manual",
    allow_agent_exec: bool = False,
    timeout_seconds: int = 120,
    auto_verify: bool = True,
    complete: bool = True,
    close_goal_on_complete: bool = False,
    render: bool = True,
    retry_run_id: str | None = None,
    resume_run_id: str | None = None,
) -> dict[str, Any]:
    require_initialized(paths)
    timeout_seconds = _normalize_timeout(timeout_seconds)
    if retry_run_id and resume_run_id:
        raise InvalidInputError(
            "--retry and --resume are mutually exclusive.",
            details={"workflow_id": workflow_id, "retry": retry_run_id, "resume": resume_run_id},
        )
    if complete and not auto_verify:
        raise InvalidInputError(
            "--no-auto-verify requires --no-complete.",
            details={"workflow_id": workflow_id, "auto_verify": auto_verify, "complete": complete},
        )

    template = load_workflow_template(paths, workflow_id)
    retry_context: dict[str, Any] | None = None
    resume_context: dict[str, Any] | None = None
    execution_mode = "new"
    if retry_run_id:
        retry_context = _load_retry_context(paths, retry_run_id, workflow_id=workflow_id)
        goal_id, defect_id = _merged_execution_targets(
            supplied_goal_id=goal_id,
            supplied_defect_id=defect_id,
            source=retry_context,
            mode="retry",
        )
        execution_mode = "retry"
    if resume_run_id:
        resume_context = _load_resume_context(paths, resume_run_id, workflow_id=workflow_id)
        goal_id, defect_id = _merged_execution_targets(
            supplied_goal_id=goal_id,
            supplied_defect_id=defect_id,
            source=resume_context,
            mode="resume",
        )
        execution_mode = "resume"
    if close_goal_on_complete and not goal_id:
        raise InvalidInputError("--close-goal requires --goal.", details={"workflow_id": workflow_id})

    verification = verify_workflow_template(paths, workflow_id=workflow_id)
    if not verification["ok"]:
        raise InvalidInputError(
            f"Workflow template {workflow_id} failed verification.",
            details={"workflow_id": workflow_id, "errors": verification["errors"]},
        )
    sandbox = plan_workflow_template_sandbox(paths, workflow_id=workflow_id, timeout_seconds=timeout_seconds)
    _require_no_blocked_commands(sandbox)
    agent_steps = _agent_steps(template)
    _require_executable_steps(workflow_id=workflow_id, sandbox=sandbox, agent_steps=agent_steps)
    if agent_steps and (not allow_agent_exec or agent_adapter not in EXECUTABLE_AGENT_ADAPTERS):
        raise InvalidInputError(
            "Workflow contains agent steps. Automatic agent execution requires "
            "--allow-agent-exec with --agent-adapter generic_shell or codex_exec.",
            details={
                "workflow_id": workflow_id,
                "agent_steps": [str(step.get("id") or "") for step in agent_steps],
                "agent_adapter": agent_adapter,
                "allow_agent_exec": allow_agent_exec,
            },
        )

    if resume_context is not None:
        run_result = _resume_workflow_run_result(paths, resume_context)
    else:
        retry_iteration = int(retry_context["iteration"] or 1) + 1 if retry_context is not None else 1
        run_result = run_workflow(
            paths,
            workflow_id=workflow_id,
            goal_id=goal_id,
            defect_id=defect_id,
            iteration=retry_iteration,
            retry_of_workflow_run_id=retry_context["id"] if retry_context is not None else None,
            retry_of_status=retry_context["status"] if retry_context is not None else None,
        )
    run_id = str(run_result["workflow_run"]["id"])
    execution_dir = paths.evidence_dir / "workflow-executions" / run_id
    execution_dir.mkdir(parents=True, exist_ok=True)
    result = _initial_result(
        workflow_id=workflow_id,
        workflow_run_id=run_id,
        goal_id=goal_id,
        defect_id=defect_id,
        agent_adapter=agent_adapter,
        allow_agent_exec=allow_agent_exec,
        timeout_seconds=timeout_seconds,
        verification=verification,
        sandbox=sandbox,
        jobs=run_result["jobs"],
        execution_mode=execution_mode,
        retry_of_workflow_run_id=retry_context["id"] if retry_context else "",
        resumed_from_workflow_run_id=resume_context["id"] if resume_context else "",
    )
    if resume_context is not None:
        _mark_execution_resumed(paths, result)
    else:
        _mark_execution_started(paths, result)

    commands_by_step = _commands_by_step(sandbox)
    jobs_by_step = {str(job["step_id"]): dict(job) for job in run_result["jobs"]}

    try:
        failed = False
        for raw_step in template.steps:
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("id") or "")
            if "agent" in raw_step:
                if step_id not in jobs_by_step:
                    raise InvalidInputError(
                        f"Workflow run {run_id} is missing an agent job for step {step_id}.",
                        details={"workflow_run_id": run_id, "workflow_id": workflow_id, "step_id": step_id},
                    )
                outcome = _execute_agent_step(
                    paths,
                    step=raw_step,
                    job=jobs_by_step[step_id],
                    adapter=agent_adapter,
                    execution_dir=execution_dir,
                    timeout_seconds=timeout_seconds,
                )
                result["steps"].append(outcome)
                if outcome["status"] == "failed":
                    result["status"] = "failed"
                    result["ok"] = False
                    result["failure_reason"] = outcome["summary"]
                    failed = True
                    break
            for command in commands_by_step.get(step_id, []):
                outcome = _execute_command_step(
                    paths,
                    step_id=step_id,
                    command=command,
                    execution_dir=execution_dir,
                    timeout_seconds=timeout_seconds,
                )
                result["steps"].append(outcome)
                if outcome["status"] == "failed":
                    fail_workflow_run(paths, workflow_run_id=run_id, summary=outcome["summary"])
                    result["status"] = "failed"
                    result["ok"] = False
                    result["failure_reason"] = outcome["summary"]
                    failed = True
                    break
            if failed:
                break

        if not failed:
            result["status"] = "passed"
            evidence_id = _record_execution_evidence(paths, result)
            result["evidence_id"] = evidence_id
            if auto_verify:
                verification_result = record_verification(
                    paths,
                    workflow_run_id=run_id,
                    result="approved",
                    reasons=[f"Workflow executor completed all steps with evidence {evidence_id}."],
                    verifier_role="workflow_executor",
                    rubric_json=json.dumps(
                        {
                            "contract_version": CONTRACT_VERSION,
                            "evidence_id": evidence_id,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                result["verification_id"] = verification_result["id"]
            if complete:
                completion = complete_workflow_run(
                    paths,
                    workflow_run_id=run_id,
                    summary=f"Workflow executor completed {workflow_id}.",
                )
                result["completion"] = completion
            if close_goal_on_complete and goal_id:
                result["goal_closure"] = close_goal(
                    paths,
                    goal_id=goal_id,
                    summary=f"Workflow executor closed goal after {workflow_id}.",
                    verification_id=result["verification_id"],
                )
        else:
            evidence_id = _record_execution_evidence(paths, result)
            result["evidence_id"] = evidence_id
    except Exception as exc:
        _capture_execution_exception(paths, result, exc)

    _mark_execution_finished(paths, result)
    _maybe_render(paths, result, enabled=render)
    _write_execution_result(paths, result)
    return result


def _execute_agent_step(
    paths: ProjectPaths,
    *,
    step: dict[str, Any],
    job: dict[str, Any],
    adapter: str,
    execution_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    step_id = str(step.get("id") or "")
    job_id = str(job["id"])
    agent_command = generate_agent_command(paths, job_id, adapter)
    if not agent_command.command:
        raise InvalidInputError(
            f"Agent adapter {adapter} does not provide an executable command.",
            details={"job_id": job_id, "adapter": adapter},
        )
    argv = shlex.split(agent_command.command)
    stdout_path = execution_dir / f"{_safe_file_token(step_id)}-{job_id}.stdout.txt"
    stderr_path = execution_dir / f"{_safe_file_token(step_id)}-{job_id}.stderr.txt"
    try:
        completed = subprocess.run(
            argv,
            cwd=paths.root,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=timeout_seconds,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr) or f"Timed out after {timeout_seconds} seconds.\n"
        timed_out = True
    stdout_path.write_text(stdout or "", encoding="utf-8")
    stderr_path.write_text(stderr or "", encoding="utf-8")
    latest_job = read_job(paths, job_id)
    passed = exit_code == 0 and latest_job["status"] == "passed"
    if not passed and latest_job["status"] in {"queued", "running", "blocked"}:
        fail_job(paths, job_id=job_id, summary=f"Agent adapter {adapter} failed for step {step_id}.")
    return {
        "kind": "agent",
        "step_id": step_id,
        "job_id": job_id,
        "adapter": adapter,
        "status": "passed" if passed else "failed",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "summary": (
            f"Agent adapter {adapter} completed job {job_id}."
            if passed
            else f"Agent adapter {adapter} failed for step {step_id}."
        ),
        "output_path": latest_job.get("output_path") or "",
        "latest_evidence_id": latest_job.get("latest_evidence_id") or "",
        "stdout_path": str(stdout_path.relative_to(paths.root)),
        "stderr_path": str(stderr_path.relative_to(paths.root)),
        "agent_command": agent_command.to_dict(),
    }


def _execute_command_step(
    paths: ProjectPaths,
    *,
    step_id: str,
    command: dict[str, Any],
    execution_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = dict(command)
    execute_planned_sandbox_command(
        paths,
        command,
        run_dir=execution_dir,
        timeout_seconds=timeout_seconds,
    )
    status = str(command["status"])
    raw_command = str(command["raw_command"])
    return {
        "kind": "command",
        "step_id": step_id,
        "command_id": command["id"],
        "raw_command": raw_command,
        "resolved_command": command["resolved_command"],
        "status": status,
        "exit_code": command["exit_code"],
        "timed_out": command["timed_out"],
        "summary": (
            f"Command step {step_id} passed: {raw_command}"
            if status == "passed"
            else f"Command step {step_id} failed: {raw_command}"
        ),
        "stdout_path": command["stdout_path"],
        "stderr_path": command["stderr_path"],
    }


def _record_execution_evidence(paths: ProjectPaths, result: dict[str, Any]) -> str:
    result["evidence_path"] = f".project-loop/evidence/workflow-executions/{result['workflow_run_id']}/result.json"
    conn = connect(paths.db_path)
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        result["evidence_id"] = evidence_id
        _write_execution_result(paths, result)
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                "workflow_execution",
                result["evidence_path"],
                _execution_command(result),
                _execution_summary(result),
                utc_now_iso(),
            ),
        )
        conn.commit()
        return evidence_id
    finally:
        conn.close()


def _load_retry_context(paths: ProjectPaths, workflow_run_id: str, *, workflow_id: str) -> dict[str, Any]:
    context = _load_workflow_run_context(paths, workflow_run_id)
    _require_same_workflow(context, workflow_id, mode="retry")
    status = str(context["status"])
    if status not in RETRYABLE_RUN_STATUSES:
        raise InvalidInputError(
            f"Workflow run {workflow_run_id} cannot be retried from status {status}.",
            details={
                "workflow_run_id": workflow_run_id,
                "workflow_id": workflow_id,
                "status": status,
                "allowed_statuses": sorted(RETRYABLE_RUN_STATUSES),
            },
        )
    existing_retry = _existing_retry_for_source(paths, workflow_run_id)
    if existing_retry:
        raise InvalidInputError(
            f"Workflow run {workflow_run_id} has already been retried by {existing_retry}.",
            details={
                "workflow_run_id": workflow_run_id,
                "workflow_id": workflow_id,
                "retry_workflow_run_id": existing_retry,
            },
        )
    return context


def _load_resume_context(paths: ProjectPaths, workflow_run_id: str, *, workflow_id: str) -> dict[str, Any]:
    context = _load_workflow_run_context(paths, workflow_run_id)
    _require_same_workflow(context, workflow_id, mode="resume")
    status = str(context["status"])
    if status not in ACTIVE_RUN_STATUSES:
        raise InvalidInputError(
            f"Workflow run {workflow_run_id} cannot be resumed from status {status}.",
            details={
                "workflow_run_id": workflow_run_id,
                "workflow_id": workflow_id,
                "status": status,
                "allowed_statuses": sorted(ACTIVE_RUN_STATUSES),
            },
        )
    if _latest_execution_has_finished(paths, workflow_run_id):
        raise InvalidInputError(
            f"Workflow run {workflow_run_id} already has a finished executor result.",
            details={"workflow_run_id": workflow_run_id, "workflow_id": workflow_id, "status": status},
        )
    return context


def _load_workflow_run_context(paths: ProjectPaths, workflow_run_id: str) -> dict[str, Any]:
    _validate_identifier(workflow_run_id, "workflow_run_id")
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT id, workflow_id, goal_id, status, iteration, started_at, ended_at, summary
            FROM workflow_runs
            WHERE id = ?
            """,
            (workflow_run_id,),
        ).fetchone()
        if row is None:
            raise InvalidInputError(
                f"Workflow run does not exist: {workflow_run_id}",
                details={"workflow_run_id": workflow_run_id},
            )
        context = dict(row)
        context["defect_id"] = _workflow_run_defect_id(conn, workflow_run_id)
        return context
    finally:
        conn.close()


def _workflow_run_defect_id(conn, workflow_run_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT payload_json
        FROM events
        WHERE entity_type = 'workflow_run'
          AND entity_id = ?
          AND event_type = 'workflow_run_created'
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (workflow_run_id,),
    ).fetchone()
    if row is None:
        return None
    payload = _parse_payload(str(row["payload_json"] or "{}"))
    defect_id = payload.get("defect_id")
    return defect_id if isinstance(defect_id, str) and defect_id else None


def _existing_retry_for_source(paths: ProjectPaths, workflow_run_id: str) -> str:
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT entity_id, payload_json
            FROM events
            WHERE event_type = 'workflow_execution_retried'
            ORDER BY rowid
            """
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        payload = _parse_payload(str(row["payload_json"] or "{}"))
        if payload.get("retry_of_workflow_run_id") == workflow_run_id:
            return str(row["entity_id"])
    return ""


def _require_same_workflow(context: dict[str, Any], workflow_id: str, *, mode: str) -> None:
    source_workflow_id = str(context["workflow_id"])
    if source_workflow_id != workflow_id:
        raise InvalidInputError(
            f"Cannot {mode} workflow run {context['id']} with workflow {workflow_id}.",
            details={
                "workflow_run_id": context["id"],
                "source_workflow_id": source_workflow_id,
                "requested_workflow_id": workflow_id,
            },
        )


def _merged_execution_targets(
    *,
    supplied_goal_id: str | None,
    supplied_defect_id: str | None,
    source: dict[str, Any],
    mode: str,
) -> tuple[str | None, str | None]:
    source_goal_id = source.get("goal_id")
    source_defect_id = source.get("defect_id")
    if supplied_goal_id and source_goal_id and supplied_goal_id != source_goal_id:
        raise InvalidInputError(
            f"Cannot {mode} workflow run {source['id']} with a different goal.",
            details={
                "workflow_run_id": source["id"],
                "source_goal_id": source_goal_id,
                "requested_goal_id": supplied_goal_id,
            },
        )
    if supplied_defect_id and source_defect_id and supplied_defect_id != source_defect_id:
        raise InvalidInputError(
            f"Cannot {mode} workflow run {source['id']} with a different defect.",
            details={
                "workflow_run_id": source["id"],
                "source_defect_id": source_defect_id,
                "requested_defect_id": supplied_defect_id,
            },
        )
    return supplied_goal_id or source_goal_id, supplied_defect_id or source_defect_id


def _resume_workflow_run_result(paths: ProjectPaths, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "workflow_run": {
            "id": context["id"],
            "workflow_id": context["workflow_id"],
            "goal_id": context["goal_id"],
            "defect_id": context["defect_id"],
            "status": context["status"],
            "iteration": context["iteration"],
        },
        "jobs": _jobs_for_workflow_run(paths, str(context["id"])),
    }


def _jobs_for_workflow_run(paths: ProjectPaths, workflow_run_id: str) -> list[dict[str, Any]]:
    conn = connect(paths.db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, workflow_run_id, role, status, prompt_path, output_path, summary
            FROM agent_jobs
            WHERE workflow_run_id = ?
            ORDER BY id
            """,
            (workflow_run_id,),
        ).fetchall()
        jobs: list[dict[str, Any]] = []
        for row in rows:
            job = dict(row)
            job["step_id"] = _step_id_from_job_summary(str(job.get("summary") or ""))
            jobs.append(job)
        return jobs
    finally:
        conn.close()


def _step_id_from_job_summary(summary: str) -> str:
    prefix = "step:"
    return summary.removeprefix(prefix) if summary.startswith(prefix) else ""


def _mark_execution_started(paths: ProjectPaths, result: dict[str, Any]) -> None:
    conn = connect(paths.db_path)
    try:
        now = utc_now_iso()
        conn.execute("UPDATE workflow_runs SET status = ? WHERE id = ?", ("running", result["workflow_run_id"]))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_execution_started",
            entity_type="workflow_run",
            entity_id=result["workflow_run_id"],
            payload={
                "contract_version": CONTRACT_VERSION,
                "workflow_id": result["workflow_id"],
                "goal_id": result["goal_id"],
                "defect_id": result["defect_id"],
                "agent_adapter": result["agent_adapter"],
                "allow_agent_exec": result["allow_agent_exec"],
                "execution_mode": result["execution_mode"],
                "retry_of_workflow_run_id": result["retry_of_workflow_run_id"],
                "started_at": now,
            },
        )
        conn.commit()
    finally:
        conn.close()


def _mark_execution_resumed(paths: ProjectPaths, result: dict[str, Any]) -> None:
    conn = connect(paths.db_path)
    try:
        now = utc_now_iso()
        previous = conn.execute(
            "SELECT status FROM workflow_runs WHERE id = ?",
            (result["workflow_run_id"],),
        ).fetchone()
        previous_status = str(previous["status"]) if previous else ""
        conn.execute("UPDATE workflow_runs SET status = ? WHERE id = ?", ("running", result["workflow_run_id"]))
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_execution_resumed",
            entity_type="workflow_run",
            entity_id=result["workflow_run_id"],
            payload={
                "contract_version": CONTRACT_VERSION,
                "workflow_id": result["workflow_id"],
                "goal_id": result["goal_id"],
                "defect_id": result["defect_id"],
                "agent_adapter": result["agent_adapter"],
                "allow_agent_exec": result["allow_agent_exec"],
                "execution_mode": result["execution_mode"],
                "previous_status": previous_status,
                "resumed_at": now,
            },
        )
        conn.commit()
    finally:
        conn.close()


def _mark_execution_finished(paths: ProjectPaths, result: dict[str, Any]) -> None:
    conn = connect(paths.db_path)
    try:
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_execution_finished",
            entity_type="workflow_run",
            entity_id=result["workflow_run_id"],
            payload={
                "contract_version": CONTRACT_VERSION,
                "workflow_id": result["workflow_id"],
                "status": result["status"],
                "ok": result["ok"],
                "execution_mode": result["execution_mode"],
                "retry_of_workflow_run_id": result["retry_of_workflow_run_id"],
                "resumed_from_workflow_run_id": result["resumed_from_workflow_run_id"],
                "evidence_id": result["evidence_id"],
                "evidence_path": result["evidence_path"],
                "verification_id": result["verification_id"],
                "step_count": len(result["steps"]),
                "failure_reason": result["failure_reason"],
            },
        )
        conn.commit()
    finally:
        conn.close()


def _latest_execution_has_finished(paths: ProjectPaths, workflow_run_id: str) -> bool:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            """
            SELECT event_type
            FROM events
            WHERE entity_type = 'workflow_run'
              AND entity_id = ?
              AND event_type IN ('workflow_execution_started', 'workflow_execution_resumed', 'workflow_execution_finished')
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (workflow_run_id,),
        ).fetchone()
        return row is not None and row["event_type"] == "workflow_execution_finished"
    finally:
        conn.close()


def _capture_execution_exception(paths: ProjectPaths, result: dict[str, Any], exc: Exception) -> None:
    summary = f"Workflow executor failed unexpectedly: {exc.__class__.__name__}: {exc}"
    result["ok"] = False
    result["status"] = "failed"
    result["failure_reason"] = summary
    result["steps"].append(
        {
            "kind": "executor_error",
            "status": "failed",
            "summary": summary,
            "error_type": exc.__class__.__name__,
        }
    )
    _fail_workflow_run_if_active(paths, str(result["workflow_run_id"]), summary=summary)
    if not result["evidence_id"]:
        result["evidence_id"] = _record_execution_evidence(paths, result)
    else:
        _write_execution_result(paths, result)


def _fail_workflow_run_if_active(paths: ProjectPaths, workflow_run_id: str, *, summary: str) -> None:
    status = _workflow_run_status(paths, workflow_run_id)
    if status in ACTIVE_RUN_STATUSES:
        fail_workflow_run(paths, workflow_run_id=workflow_run_id, summary=summary)


def _workflow_run_status(paths: ProjectPaths, workflow_run_id: str) -> str:
    conn = connect(paths.db_path)
    try:
        row = conn.execute("SELECT status FROM workflow_runs WHERE id = ?", (workflow_run_id,)).fetchone()
        return str(row["status"]) if row else ""
    finally:
        conn.close()


def _maybe_render(paths: ProjectPaths, result: dict[str, Any], *, enabled: bool) -> None:
    validation = validate_project(paths)
    result["validation"] = validation.to_dict()
    if not enabled:
        result["rendered"] = False
        return
    if not validation.ok:
        result["rendered"] = False
        return
    render_dashboard(paths)
    result["rendered"] = True
    result["dashboard_path"] = str(paths.dashboard_html)


def _write_execution_result(paths: ProjectPaths, result: dict[str, Any]) -> None:
    evidence_path = result.get("evidence_path")
    if not evidence_path:
        return
    path = paths.root / str(evidence_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_no_blocked_commands(sandbox: dict[str, Any]) -> None:
    if not sandbox["verification"]["ok"]:
        raise InvalidInputError(
            f"Workflow template {sandbox['target_id']} failed verification.",
            details={"workflow_id": sandbox["target_id"], "errors": sandbox["verification"]["errors"]},
        )
    blocked = [command for command in sandbox["commands"] if not command["safe_to_run"]]
    if blocked:
        raise InvalidInputError(
            f"Workflow {sandbox['target_id']} contains command steps blocked by the sandbox.",
            details={
                "workflow_id": sandbox["target_id"],
                "blocked_commands": [
                    {
                        "step_id": command["step_id"],
                        "raw_command": command["raw_command"],
                        "blocked_reason": command["blocked_reason"],
                    }
                    for command in blocked
                ],
            },
        )


def _require_executable_steps(
    *,
    workflow_id: str,
    sandbox: dict[str, Any],
    agent_steps: list[dict[str, Any]],
) -> None:
    command_count = int(sandbox.get("command_count") or 0)
    agent_step_count = len(agent_steps)
    if command_count or agent_step_count:
        return
    raise InvalidInputError(
        f"Workflow {workflow_id} has no executable command or agent steps.",
        details={
            "workflow_id": workflow_id,
            "command_count": command_count,
            "agent_step_count": agent_step_count,
        },
    )


def _commands_by_step(sandbox: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for command in sandbox["commands"]:
        grouped.setdefault(str(command["step_id"]), []).append(dict(command))
    return grouped


def _agent_steps(template: WorkflowTemplate) -> list[dict[str, Any]]:
    return [
        dict(step)
        for step in template.steps
        if isinstance(step, dict) and "agent" in step
    ]


def _initial_result(
    *,
    workflow_id: str,
    workflow_run_id: str,
    goal_id: str | None,
    defect_id: str | None,
    agent_adapter: str,
    allow_agent_exec: bool,
    timeout_seconds: int,
    verification: dict[str, Any],
    sandbox: dict[str, Any],
    jobs: list[dict[str, Any]],
    execution_mode: str,
    retry_of_workflow_run_id: str,
    resumed_from_workflow_run_id: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "goal_id": goal_id,
        "defect_id": defect_id,
        "status": "running",
        "agent_adapter": agent_adapter,
        "allow_agent_exec": allow_agent_exec,
        "timeout_seconds": timeout_seconds,
        "workflow_verification": verification,
        "execution_mode": execution_mode,
        "retry_of_workflow_run_id": retry_of_workflow_run_id,
        "resumed_from_workflow_run_id": resumed_from_workflow_run_id,
        "sandbox": {
            "contract_version": sandbox["contract_version"],
            "command_count": sandbox["command_count"],
            "safe_command_count": sandbox["safe_command_count"],
            "blocked_command_count": sandbox["blocked_command_count"],
        },
        "jobs": jobs,
        "steps": [],
        "failure_reason": "",
        "evidence_id": "",
        "evidence_path": "",
        "verification_id": "",
        "completion": None,
        "goal_closure": None,
        "validation": None,
        "rendered": False,
        "dashboard_path": "",
    }


def _execution_command(result: dict[str, Any]) -> str:
    command = f"pcl loop execute {result['workflow_id']}"
    if result["retry_of_workflow_run_id"]:
        command += f" --retry {result['retry_of_workflow_run_id']}"
    if result["resumed_from_workflow_run_id"]:
        command += f" --resume {result['resumed_from_workflow_run_id']}"
    if result["goal_id"]:
        command += f" --goal {result['goal_id']}"
    if result["defect_id"]:
        command += f" --defect {result['defect_id']}"
    if result["allow_agent_exec"]:
        command += f" --agent-adapter {result['agent_adapter']} --allow-agent-exec"
    return command


def _execution_summary(result: dict[str, Any]) -> str:
    return (
        f"Workflow executor {result['status']}: workflow={result['workflow_id']} "
        f"run={result['workflow_run_id']} mode={result['execution_mode']} steps={len(result['steps'])}"
    )


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _safe_file_token(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value) or "step"


def _normalize_timeout(timeout_seconds: int) -> int:
    if timeout_seconds < 1:
        raise InvalidInputError(
            "Workflow executor timeout must be at least 1 second.",
            details={"timeout_seconds": timeout_seconds},
        )
    if timeout_seconds > 600:
        raise InvalidInputError(
            "Workflow executor timeout must be 600 seconds or less.",
            details={"timeout_seconds": timeout_seconds},
        )
    return timeout_seconds


def _validate_identifier(value: str, field_name: str) -> None:
    if not value or not all(char.isalnum() or char in {"_", "-"} for char in value):
        raise InvalidInputError(
            f"Invalid {field_name}: {value}",
            details={field_name: value},
        )


def _parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
