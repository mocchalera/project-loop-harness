from __future__ import annotations

from .registry import AGENT_STATUSES
from .workflow_proposals import PROPOSAL_STATUSES


def add_execution_parsers(sub) -> None:
    p_loop = sub.add_parser("loop", help="Inspect or run loops")
    loop_sub = p_loop.add_subparsers(dest="loop_command", required=True)
    loop_sub.add_parser("status", help="Print loop status")
    p_loop_run = loop_sub.add_parser("run", help="Placeholder for workflow execution")
    p_loop_run.add_argument("workflow_id")
    p_loop_run.add_argument("--goal", default=None)
    p_loop_run.add_argument("--defect", default=None)
    p_loop_execute = loop_sub.add_parser(
        "execute",
        help="Execute an approved workflow through the guarded executor (host subprocess, no OS isolation)",
    )
    p_loop_execute.add_argument("workflow_id")
    p_loop_execute.add_argument("--goal", default=None)
    p_loop_execute.add_argument("--defect", default=None)
    p_loop_execute.add_argument(
        "--agent-adapter",
        default="manual",
        choices=["manual", "generic_shell", "codex_exec"],
        help="Executable adapter for agent steps. Defaults to manual, which cannot auto-execute.",
    )
    p_loop_execute.add_argument("--allow-agent-exec", action="store_true")
    p_loop_execute.add_argument("--timeout-seconds", type=int, default=120)
    p_loop_execute.add_argument("--max-output-bytes", type=int, default=1_048_576)
    p_loop_execute.add_argument(
        "--redact-pattern",
        action="append",
        default=[],
        help="Additional Python regex applied before execution output is stored. Repeatable.",
    )
    p_loop_execute.add_argument(
        "--allow-env",
        action="append",
        default=[],
        metavar="NAME",
        help="Explicitly inherit an additional environment variable by name. Repeatable.",
    )
    p_loop_execute.add_argument("--no-auto-verify", action="store_true")
    p_loop_execute.add_argument("--no-complete", action="store_true")
    p_loop_execute.add_argument("--close-goal", action="store_true")
    p_loop_execute.add_argument("--no-render", action="store_true")
    execute_recovery = p_loop_execute.add_mutually_exclusive_group()
    execute_recovery.add_argument("--retry", dest="retry_run", default=None, metavar="WR-0001")
    execute_recovery.add_argument("--resume", dest="resume_run", default=None, metavar="WR-0001")
    p_loop_complete = loop_sub.add_parser("complete", help="Mark a workflow run passed")
    p_loop_complete.add_argument("workflow_run_id")
    p_loop_complete.add_argument("--summary", required=True)
    p_loop_fail = loop_sub.add_parser("fail", help="Mark a workflow run failed")
    p_loop_fail.add_argument("workflow_run_id")
    p_loop_fail.add_argument("--summary", required=True)
    p_loop_cancel = loop_sub.add_parser("cancel", help="Cancel a workflow run and its active jobs")
    p_loop_cancel.add_argument("workflow_run_id")
    p_loop_cancel.add_argument("--summary", required=True)

    p_workflow = sub.add_parser("workflow", help="Manage workflow proposals")
    workflow_sub = p_workflow.add_subparsers(dest="workflow_command", required=True)
    p_workflow_propose = workflow_sub.add_parser(
        "propose", help="Store a workflow proposal for review"
    )
    p_workflow_propose.add_argument("--file", required=True, help="Workflow YAML file to propose")
    p_workflow_propose.add_argument("--summary", default="")
    p_workflow_verify = workflow_sub.add_parser(
        "verify", help="Verify a workflow file, proposal, or template"
    )
    workflow_verify_target = p_workflow_verify.add_mutually_exclusive_group(required=True)
    workflow_verify_target.add_argument("--file", default=None, help="Workflow YAML file to verify")
    workflow_verify_target.add_argument(
        "--proposal", default=None, help="Workflow proposal id to verify"
    )
    workflow_verify_target.add_argument(
        "--template", default=None, help="Approved workflow template id to verify"
    )
    p_workflow_guard = workflow_sub.add_parser(
        "guard",
        help="Plan or run allowlisted commands on the host (no OS/network/filesystem isolation)",
    )
    workflow_guard_target = p_workflow_guard.add_mutually_exclusive_group(required=True)
    workflow_guard_target.add_argument("--file", default=None, help="Workflow YAML file to inspect")
    workflow_guard_target.add_argument(
        "--proposal", default=None, help="Workflow proposal id to inspect"
    )
    workflow_guard_target.add_argument(
        "--template", default=None, help="Approved workflow template id"
    )
    p_workflow_guard.add_argument(
        "--execute", action="store_true", help="Run guarded allowlisted commands"
    )
    p_workflow_guard.add_argument("--timeout-seconds", type=int, default=120)
    p_workflow_guard.add_argument("--max-output-bytes", type=int, default=1_048_576)
    p_workflow_guard.add_argument(
        "--redact-pattern",
        action="append",
        default=[],
        help="Additional Python regex applied before execution output is stored. Repeatable.",
    )
    p_workflow_guard.add_argument(
        "--allow-env",
        action="append",
        default=[],
        metavar="NAME",
        help="Explicitly inherit an additional environment variable by name. Repeatable.",
    )
    p_workflow_sandbox = workflow_sub.add_parser(
        "sandbox",
        help="Deprecated alias for `workflow guard`; retained through the 0.3.x release line",
    )
    workflow_sandbox_target = p_workflow_sandbox.add_mutually_exclusive_group(required=True)
    workflow_sandbox_target.add_argument(
        "--file", default=None, help="Workflow YAML file to inspect"
    )
    workflow_sandbox_target.add_argument(
        "--proposal", default=None, help="Workflow proposal id to inspect"
    )
    workflow_sandbox_target.add_argument(
        "--template", default=None, help="Approved workflow template id"
    )
    p_workflow_sandbox.add_argument(
        "--execute", action="store_true", help="Run guarded allowlisted commands"
    )
    p_workflow_sandbox.add_argument("--timeout-seconds", type=int, default=120)
    p_workflow_sandbox.add_argument("--max-output-bytes", type=int, default=1_048_576)
    p_workflow_sandbox.add_argument("--allow-env", action="append", default=[], metavar="NAME")
    p_workflow_proposals = workflow_sub.add_parser("proposals", help="Inspect workflow proposals")
    proposals_sub = p_workflow_proposals.add_subparsers(
        dest="workflow_proposals_command", required=True
    )
    p_workflow_proposals_list = proposals_sub.add_parser("list", help="List workflow proposals")
    p_workflow_proposals_list.add_argument(
        "--status", choices=sorted(PROPOSAL_STATUSES), default=None
    )
    p_workflow_proposals_read = proposals_sub.add_parser("read", help="Read a workflow proposal")
    p_workflow_proposals_read.add_argument("proposal_id")
    p_workflow_proposals_approve = proposals_sub.add_parser(
        "approve", help="Approve a workflow proposal"
    )
    p_workflow_proposals_approve.add_argument("proposal_id")
    p_workflow_proposals_approve.add_argument("--summary", required=True)
    p_workflow_proposals_cancel = proposals_sub.add_parser(
        "cancel", help="Cancel a workflow proposal"
    )
    p_workflow_proposals_cancel.add_argument("proposal_id")
    p_workflow_proposals_cancel.add_argument("--summary", required=True)

    p_jobs = sub.add_parser("jobs", help="Inspect agent jobs")
    jobs_sub = p_jobs.add_subparsers(dest="jobs_command", required=True)
    p_jobs_list = jobs_sub.add_parser("list", help="List agent jobs")
    p_jobs_list.add_argument("--run", default=None, help="Filter jobs by workflow run id")
    p_jobs_list.add_argument(
        "--status",
        choices=["queued", "running", "blocked", "failed", "passed", "cancelled"],
        default=None,
        help="Filter jobs by job status",
    )
    p_jobs_read = jobs_sub.add_parser("read", help="Read an agent job prompt")
    p_jobs_read.add_argument("job_id")
    p_jobs_complete = jobs_sub.add_parser("complete", help="Mark an agent job passed")
    p_jobs_complete.add_argument("job_id")
    p_jobs_complete.add_argument("--summary", required=True)
    p_jobs_complete.add_argument("--output", default=None)
    p_jobs_complete.add_argument(
        "--evidence", default=None, help="Existing evidence ID to link to this completion"
    )
    p_jobs_complete.add_argument("--token-input", type=int, default=None)
    p_jobs_complete.add_argument("--token-output", type=int, default=None)
    p_jobs_fail = jobs_sub.add_parser("fail", help="Mark an agent job failed")
    p_jobs_fail.add_argument("job_id")
    p_jobs_fail.add_argument("--summary", required=True)
    p_jobs_cancel = jobs_sub.add_parser("cancel", help="Cancel an agent job")
    p_jobs_cancel.add_argument("job_id")
    p_jobs_cancel.add_argument("--summary", required=True)
    p_jobs_assign = jobs_sub.add_parser("assign", help="Assign a queued job to an agent")
    p_jobs_assign.add_argument("job_id")
    p_jobs_assign.add_argument("--agent", required=True, help="Agent registry id")
    p_jobs_lease = jobs_sub.add_parser("lease", help="Lease a queued job for an agent")
    p_jobs_lease.add_argument("job_id")
    p_jobs_lease.add_argument("--agent", required=True, help="Agent registry id")
    p_jobs_lease.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help="Lease TTL in seconds. Defaults to loop.lease_ttl_seconds or 1800.",
    )
    p_jobs_heartbeat = jobs_sub.add_parser("heartbeat", help="Extend a running job lease")
    p_jobs_heartbeat.add_argument("job_id")
    p_jobs_heartbeat.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help="Lease TTL in seconds. Defaults to loop.lease_ttl_seconds or 1800.",
    )
    p_jobs_release = jobs_sub.add_parser(
        "release", help="Release a running job lease back to queued"
    )
    p_jobs_release.add_argument("job_id")
    p_jobs_release.add_argument("--reason", required=True)
    jobs_sub.add_parser("reap", help="Requeue or block expired job leases")

    p_prompt = sub.add_parser("prompt", help="Print generated prompts")
    prompt_sub = p_prompt.add_subparsers(dest="prompt_command", required=True)
    p_prompt_job = prompt_sub.add_parser("job", help="Print one agent job prompt")
    p_prompt_job.add_argument("job_id")

    p_agent = sub.add_parser("agent", help="Manage agents and generate adapter commands")
    agent_sub = p_agent.add_subparsers(dest="agent_command", required=True)
    p_agent_command = agent_sub.add_parser("command", help="Print an adapter command for a job")
    p_agent_command.add_argument("job_id")
    p_agent_command.add_argument(
        "--adapter",
        default="manual",
        choices=["manual", "codex_exec", "claude_manual", "generic_shell"],
        help="Agent adapter to use. Defaults to manual.",
    )
    p_agent_register = agent_sub.add_parser("register", help="Register an agent")
    p_agent_register.add_argument("--name", required=True)
    p_agent_register.add_argument("--role", required=True)
    p_agent_register.add_argument(
        "--adapter",
        required=True,
        choices=["manual", "codex_exec", "claude_manual", "generic_shell"],
    )
    p_agent_register.add_argument("--max-concurrency", type=int, default=1)
    p_agent_register.add_argument("--metadata-json", default="{}")
    p_agent_list = agent_sub.add_parser("list", help="List registered agents")
    p_agent_list.add_argument("--status", choices=sorted(AGENT_STATUSES), default=None)
    p_agent_read = agent_sub.add_parser("read", help="Read a registered agent")
    p_agent_read.add_argument("agent_id")
    p_agent_update = agent_sub.add_parser("update", help="Update a registered agent")
    p_agent_update.add_argument("agent_id")
    p_agent_update.add_argument("--name", default=None)
    p_agent_update.add_argument("--role", default=None)
    p_agent_update.add_argument(
        "--adapter",
        choices=["manual", "codex_exec", "claude_manual", "generic_shell"],
        default=None,
    )
    p_agent_update.add_argument("--max-concurrency", type=int, default=None)
    p_agent_update.add_argument("--metadata-json", default=None)
    p_agent_update.add_argument("--status", choices=["active", "paused"], default=None)
    p_agent_update.add_argument("--reason", required=True)
    p_agent_retire = agent_sub.add_parser("retire", help="Retire a registered agent")
    p_agent_retire.add_argument("agent_id")
    p_agent_retire.add_argument("--reason", required=True)

    p_ingest = sub.add_parser("ingest-agent-run", help="Record an agent output file as evidence")
    p_ingest.add_argument("path")

    p_evidence = sub.add_parser("evidence", help="Record or inspect standalone evidence artifacts")
    evidence_sub = p_evidence.add_subparsers(dest="evidence_command", required=True)
    p_evidence_add = evidence_sub.add_parser(
        "add",
        help="Record existing local files as adhoc evidence",
        epilog=(
            "--command is the caller's claim about how the artifact was produced; "
            "pcl stores it verbatim and does not run or verify it. "
            "--copy stores a byte-identical copy at record time so the artifact can "
            "survive workspace cleanup on this machine; it is not a transfer bundle. "
            "--task links the evidence row to an existing task for task context packs; "
            "PLH does not infer or verify that relationship. "
            "Sensitive evidence checks are filename-shape checks only; "
            "PLH does not scan file contents."
        ),
    )
    p_evidence_add.add_argument(
        "--file",
        action="append",
        required=True,
        dest="files",
        help="Existing readable artifact path. Repeat for bundles.",
    )
    p_evidence_add.add_argument("--summary", required=True)
    p_evidence_add.add_argument(
        "--command",
        default=None,
        dest="claimed_command",
        help="Caller claim of the producing command; stored verbatim, not run or verified.",
    )
    p_evidence_add.add_argument(
        "--allow-sensitive-evidence",
        action="store_true",
        help=(
            "Record files whose path matches sensitive filename patterns. "
            "This is an explicit caller decision; PLH does not scan file contents."
        ),
    )
    p_evidence_add.add_argument(
        "--copy",
        action="store_true",
        dest="copy_files",
        help=(
            "Copy each member into .project-loop/evidence/adhoc-files at record time. "
            "The copy is byte-identical by sha256 when recorded and survives workspace cleanup on this machine."
        ),
    )
    p_evidence_add.add_argument(
        "--task",
        default=None,
        dest="task_id",
        help="Existing task id to link this adhoc evidence row into task context packs.",
    )
    p_evidence_show = evidence_sub.add_parser(
        "show",
        help="Resolve read-only Evidence metadata without inlining artifact bodies",
    )
    p_evidence_show.add_argument("evidence_id")
    p_evidence_supersede = evidence_sub.add_parser(
        "supersede", help="Mark old Evidence as replaced while retaining its audit history"
    )
    p_evidence_supersede.add_argument("evidence_id")
    p_evidence_supersede.add_argument("--with", required=True, dest="replacement_evidence_id")
    p_evidence_supersede.add_argument("--summary", required=True)
    p_evidence_link = evidence_sub.add_parser(
        "link", help="Add one validated Evidence relationship"
    )
    p_evidence_link.add_argument("evidence_id")
    p_evidence_link.add_argument(
        "--target",
        required=True,
        dest="target_ref",
        help="Target reference as <target-type>:<target-id>",
    )
    p_evidence_link.add_argument("--role", required=True)
    p_evidence_link.add_argument("--summary", required=True)
