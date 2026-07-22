from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from .agents import (
    generate_agent_command,
    ingest_agent_run,
    read_job_prompt,
    read_job_prompt_handoff,
)
from .dispatch import assign_job, heartbeat_job, lease_job, reap_expired_leases, release_job
from .lifecycle import (
    cancel_job,
    cancel_workflow_run,
    complete_job,
    complete_workflow_run,
    fail_job,
    fail_workflow_run,
)
from .paths import ProjectPaths
from .presentation import to_pretty_json
from .registry import list_agents, read_agent, register_agent, retire_agent, update_agent
from .workflow_executor import execute_workflow
from .workflow_proposals import (
    approve_workflow_proposal,
    cancel_workflow_proposal,
    list_workflow_proposals,
    propose_workflow,
    read_workflow_proposal,
)
from .workflow_sandbox import (
    LEGACY_DEPRECATION,
    guard_workflow_file,
    guard_workflow_proposal,
    guard_workflow_template,
    sandbox_workflow_file,
    sandbox_workflow_proposal,
    sandbox_workflow_template,
)
from .workflow_verifier import (
    verify_workflow_file,
    verify_workflow_proposal,
    verify_workflow_template,
)
from .workflows import list_jobs, read_job, run_workflow


EXECUTION_COMMANDS = frozenset(
    {"loop", "workflow", "jobs", "prompt", "agent", "ingest-agent-run"}
)


def handle_execution_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int | None:
    """Handle workflow and agent execution commands, or return ``None``."""

    if args.command not in EXECUTION_COMMANDS:
        return None
    if args.command == "loop" and args.loop_command == "status":
        return None

    if args.command == "loop" and args.loop_command == "run":
        result = run_workflow(
            paths,
            workflow_id=args.workflow_id,
            goal_id=args.goal,
            defect_id=args.defect,
        )
        if json_output:
            _write_json(result, output)
        elif result.get("no_op"):
            print(
                "No workflow run created: all tracked features are already covered "
                f"({result['covered_feature_count']}).",
                file=output,
            )
        else:
            run = result["workflow_run"]
            print(f"Created workflow run {run['id']} for {run['workflow_id']}", file=output)
            for job in result["jobs"]:
                print(
                    f"Queued job {job['id']} role={job['role']} prompt={job['prompt_path']}",
                    file=output,
                )
        return 0

    if args.command == "loop" and args.loop_command == "execute":
        result = execute_workflow(
            paths,
            workflow_id=args.workflow_id,
            goal_id=args.goal,
            defect_id=args.defect,
            agent_adapter=args.agent_adapter,
            allow_agent_exec=args.allow_agent_exec,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            redaction_patterns=args.redact_pattern,
            allowed_env_names=args.allow_env,
            auto_verify=not args.no_auto_verify,
            complete=not args.no_complete,
            close_goal_on_complete=args.close_goal,
            render=not args.no_render,
            retry_run_id=args.retry_run,
            resume_run_id=args.resume_run,
        )
        _write_json(result, output) if json_output else print(
            to_pretty_json(result), file=output
        )
        return 0 if result["ok"] else 1

    if args.command == "loop" and args.loop_command == "complete":
        result = complete_workflow_run(
            paths,
            workflow_run_id=args.workflow_run_id,
            summary=args.summary,
        )
        _write_json(result, output) if json_output else print(
            f"Completed workflow run {result['workflow_run_id']}", file=output
        )
        return 0

    if args.command == "loop" and args.loop_command == "fail":
        result = fail_workflow_run(
            paths,
            workflow_run_id=args.workflow_run_id,
            summary=args.summary,
        )
        _write_json(result, output) if json_output else print(
            f"Failed workflow run {result['workflow_run_id']}", file=output
        )
        return 0

    if args.command == "loop" and args.loop_command == "cancel":
        result = cancel_workflow_run(
            paths,
            workflow_run_id=args.workflow_run_id,
            summary=args.summary,
        )
        _write_json(result, output) if json_output else print(
            f"Cancelled workflow run {result['workflow_run_id']}", file=output
        )
        return 0

    if args.command == "workflow" and args.workflow_command == "propose":
        result = propose_workflow(paths, source_path=args.file, summary=args.summary)
        _write_json(result, output) if json_output else print(result["id"], file=output)
        return 0

    if args.command == "workflow" and args.workflow_command == "verify":
        if args.file:
            result = verify_workflow_file(paths, source_path=args.file)
        elif args.proposal:
            result = verify_workflow_proposal(paths, proposal_id=args.proposal)
        else:
            result = verify_workflow_template(paths, workflow_id=args.template)
        payload = {"ok": result["ok"], "verification": result}
        _write_json(payload, output) if json_output else print(
            to_pretty_json(payload), file=output
        )
        return 0 if result["ok"] else 1

    if args.command == "workflow" and args.workflow_command in {"guard", "sandbox"}:
        legacy_alias = args.workflow_command == "sandbox"
        if legacy_alias:
            print(f"WARNING: {LEGACY_DEPRECATION}", file=error)
        file_handler = sandbox_workflow_file if legacy_alias else guard_workflow_file
        proposal_handler = (
            sandbox_workflow_proposal if legacy_alias else guard_workflow_proposal
        )
        template_handler = (
            sandbox_workflow_template if legacy_alias else guard_workflow_template
        )
        redaction_patterns = [] if legacy_alias else args.redact_pattern
        if args.file:
            result = file_handler(
                paths,
                source_path=args.file,
                execute=args.execute,
                timeout_seconds=args.timeout_seconds,
                max_output_bytes=args.max_output_bytes,
                **({"redaction_patterns": redaction_patterns} if not legacy_alias else {}),
                allowed_env_names=args.allow_env,
            )
        elif args.proposal:
            result = proposal_handler(
                paths,
                proposal_id=args.proposal,
                execute=args.execute,
                timeout_seconds=args.timeout_seconds,
                max_output_bytes=args.max_output_bytes,
                **({"redaction_patterns": redaction_patterns} if not legacy_alias else {}),
                allowed_env_names=args.allow_env,
            )
        else:
            result = template_handler(
                paths,
                workflow_id=args.template,
                execute=args.execute,
                timeout_seconds=args.timeout_seconds,
                max_output_bytes=args.max_output_bytes,
                **({"redaction_patterns": redaction_patterns} if not legacy_alias else {}),
                allowed_env_names=args.allow_env,
            )
        _write_json(result, output) if json_output else print(
            to_pretty_json(result), file=output
        )
        return 0 if result["ok"] else 1

    if args.command == "workflow" and args.workflow_command == "proposals":
        if args.workflow_proposals_command == "list":
            proposals = list_workflow_proposals(paths, status=args.status)
            if json_output:
                _write_json({"ok": True, "proposals": proposals}, output)
            elif proposals:
                for proposal in proposals:
                    print(
                        f"{proposal['id']} workflow={proposal['workflow_id']} "
                        f"path={proposal['path']}",
                        file=output,
                    )
            else:
                print("No workflow proposals", file=output)
            return 0
        if args.workflow_proposals_command == "read":
            proposal = read_workflow_proposal(paths, args.proposal_id)
            _write_json({"ok": True, "proposal": proposal}, output) if json_output else print(
                to_pretty_json(proposal), file=output
            )
            return 0
        if args.workflow_proposals_command == "approve":
            result = approve_workflow_proposal(paths, args.proposal_id, summary=args.summary)
            _write_json(result, output) if json_output else print(
                f"Approved workflow proposal {result['id']} as {result['workflow_path']}",
                file=output,
            )
            return 0
        if args.workflow_proposals_command == "cancel":
            result = cancel_workflow_proposal(paths, args.proposal_id, summary=args.summary)
            _write_json(result, output) if json_output else print(
                f"Cancelled workflow proposal {result['id']}", file=output
            )
            return 0

    if args.command == "jobs" and args.jobs_command == "list":
        jobs = list_jobs(paths, workflow_run_id=args.run, status=args.status)
        if json_output:
            _write_json({"ok": True, "jobs": jobs}, output)
        elif jobs:
            for job in jobs:
                print(
                    f"{job['id']} {job['status']} workflow={job['workflow_id']} "
                    f"run={job['workflow_run_id']} role={job['role']}",
                    file=output,
                )
        else:
            print("No agent jobs", file=output)
        return 0

    if args.command == "jobs" and args.jobs_command == "read":
        job = read_job(paths, args.job_id)
        _write_json({"ok": True, "job": job}, output) if json_output else print(
            job["prompt"], file=output
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "complete":
        result = complete_job(
            paths,
            job_id=args.job_id,
            summary=args.summary,
            output_path=args.output,
            evidence_id=args.evidence,
            token_input=args.token_input,
            token_output=args.token_output,
        )
        _write_json(result, output) if json_output else print(
            f"Completed job {result['job_id']}", file=output
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "fail":
        result = fail_job(paths, job_id=args.job_id, summary=args.summary)
        _write_json(result, output) if json_output else print(
            f"Failed job {result['job_id']}", file=output
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "cancel":
        result = cancel_job(paths, job_id=args.job_id, summary=args.summary)
        _write_json(result, output) if json_output else print(
            f"Cancelled job {result['job_id']}", file=output
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "assign":
        result = assign_job(paths, job_id=args.job_id, agent_id=args.agent)
        _write_json(result, output) if json_output else print(
            f"Assigned job {result['job_id']} to {result['assigned_agent_id']}", file=output
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "lease":
        result = lease_job(
            paths,
            job_id=args.job_id,
            agent_id=args.agent,
            ttl_seconds=args.ttl_seconds,
        )
        if json_output:
            _write_json(result, output)
        else:
            print(
                f"Leased job {result['job_id']} to {result['assigned_agent_id']} "
                f"until {result['lease_expires_at']}",
                file=output,
            )
        return 0

    if args.command == "jobs" and args.jobs_command == "heartbeat":
        result = heartbeat_job(paths, job_id=args.job_id, ttl_seconds=args.ttl_seconds)
        _write_json(result, output) if json_output else print(
            f"Heartbeat recorded for job {result['job_id']} until {result['lease_expires_at']}",
            file=output,
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "release":
        result = release_job(paths, job_id=args.job_id, reason=args.reason)
        _write_json(result, output) if json_output else print(
            f"Released job {result['job_id']}", file=output
        )
        return 0

    if args.command == "jobs" and args.jobs_command == "reap":
        result = reap_expired_leases(paths)
        if json_output:
            _write_json(result, output)
        else:
            print(
                "Reaped expired leases: "
                f"requeued={','.join(result['reaped_job_ids']) or '-'} "
                f"blocked={','.join(result['blocked_job_ids']) or '-'}",
                file=output,
            )
        return 0

    if args.command == "prompt" and args.prompt_command == "job":
        if json_output:
            _write_json(read_job_prompt_handoff(paths, args.job_id), output)
        else:
            print(read_job_prompt(paths, args.job_id), file=output)
        return 0

    if args.command == "agent" and args.agent_command == "command":
        command = generate_agent_command(paths, args.job_id, args.adapter)
        if json_output:
            _write_json({"ok": True, "agent_command": command.to_dict()}, output)
        elif command.command:
            print(command.command, file=output)
        else:
            print(command.instructions, file=output)
        return 0

    if args.command == "agent" and args.agent_command == "register":
        result = register_agent(
            paths,
            name=args.name,
            role=args.role,
            adapter=args.adapter,
            max_concurrency=args.max_concurrency,
            metadata_json=args.metadata_json,
        )
        _write_json(result, output) if json_output else print(
            f"Registered agent {result['id']}", file=output
        )
        return 0

    if args.command == "agent" and args.agent_command == "list":
        agents = list_agents(paths, status=args.status)
        if json_output:
            _write_json({"ok": True, "agents": agents}, output)
        elif agents:
            for agent in agents:
                print(
                    f"{agent['id']} {agent['status']} name={agent['name']} "
                    f"role={agent['role']} adapter={agent['adapter']} "
                    f"active_leases={agent['active_lease_count']}/{agent['max_concurrency']}",
                    file=output,
                )
        else:
            print("No agents", file=output)
        return 0

    if args.command == "agent" and args.agent_command == "read":
        agent = read_agent(paths, args.agent_id)
        _write_json({"ok": True, "agent": agent}, output) if json_output else print(
            to_pretty_json(agent), file=output
        )
        return 0

    if args.command == "agent" and args.agent_command == "update":
        result = update_agent(
            paths,
            args.agent_id,
            fields={
                "name": args.name,
                "role": args.role,
                "adapter": args.adapter,
                "max_concurrency": args.max_concurrency,
                "metadata_json": args.metadata_json,
                "status": args.status,
            },
            reason=args.reason,
        )
        _write_json(result, output) if json_output else print(
            f"Updated agent {result['agent']['id']}", file=output
        )
        return 0

    if args.command == "agent" and args.agent_command == "retire":
        result = retire_agent(paths, args.agent_id, reason=args.reason)
        _write_json(result, output) if json_output else print(
            f"Retired agent {result['agent']['id']}", file=output
        )
        return 0

    if args.command == "ingest-agent-run":
        result = ingest_agent_run(paths, args.path)
        if json_output:
            _write_json(result, output)
        else:
            print(
                f"Ingested {result['output_path']} as {result['evidence_id']} "
                f"for job {result['job_id']}",
                file=output,
            )
        return 0

    raise AssertionError(f"Unhandled execution command: {args.command}")


def _write_json(payload: object, output: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
