from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .agents import generate_agent_command, ingest_agent_run, read_job_prompt, read_job_prompt_handoff
from .checkpoints import checkpoint_status, record_checkpoint
from .code_index import (
    GIT_DIFF_SENTINEL,
    analyze_impact,
    build_code_index,
    code_index_status,
    compare_retrieval_baseline,
    evaluate_retrieval,
    propose_retrieval_fixture,
    record_retrieval_baseline,
    search_code,
)
from .commands import (
    FEATURE_STATUSES,
    add_feature,
    build_next_action,
    create_goal,
    finish_plan,
    list_features,
    loop_status,
    next_action,
    open_defect,
    read_feature,
    set_feature_status,
    to_pretty_json,
)
from .context import (
    DEFAULT_MAX_TOKENS,
    context_check_for_job,
    context_check_for_task,
    pack_context_for_job,
    pack_context_for_task,
)
from .code_context.summary import render_receipt_summary
from .decisions import (
    list_decisions,
    open_decision,
    read_decision,
    resolve_decision,
    waive_decision,
)
from .dispatch import assign_job, heartbeat_job, lease_job, reap_expired_leases, release_job
from .evidence import record_adhoc_evidence
from .errors import DataStoreError, InvalidInputError, PclError
from .exporters import export_csv
from .escalations import (
    cancel_escalation,
    list_escalations,
    open_escalation,
    read_escalation,
    resolve_escalation,
)
from .init_project import init_project, plan_init_project
from .lifecycle import (
    cancel_goal,
    cancel_job,
    cancel_workflow_run,
    close_goal,
    close_defect,
    complete_job,
    complete_workflow_run,
    fail_job,
    fail_workflow_run,
    fix_defect,
    record_verification,
    start_defect,
    triage_defect,
    verify_defect,
    waive_defect,
)
from .migrations import apply_migrations, migration_status
from .paths import resolve_paths
from .renderer import render_dashboard
from .receipt_show import receipt_summary_for_ref
from .registry import AGENT_STATUSES, list_agents, read_agent, register_agent, retire_agent, update_agent
from .reports import report_defect, report_feature, report_goal, report_run, report_validation
from .stories import (
    STORY_STATUSES,
    TEST_CASE_STATUSES,
    TEST_CASE_TYPES,
    approve_story,
    block_test_case,
    draft_story,
    fail_test_case,
    list_stories,
    list_test_cases,
    missing_test_case,
    pass_test_case,
    plan_test_case,
    read_story,
    read_test_case,
    review_story,
    waive_story,
    waive_test_case,
)
from .timeutil import utc_now_iso
from .tasks import (
    TASK_RISKS,
    TASK_STATUSES,
    add_dependency,
    create_task,
    list_tasks,
    read_task,
    remove_dependency,
    set_task_status,
)
from . import update_check
from .validators import validate_project
from .verification_feedback import record_verification_feedback, verification_feedback_stats
from .verifications import VERIFICATION_RESULTS, list_verifications, read_verification
from .workflow_proposals import (
    PROPOSAL_STATUSES,
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
from .workflow_verifier import verify_workflow_file, verify_workflow_proposal, verify_workflow_template
from .workflow_executor import execute_workflow
from .workflows import list_jobs, read_job, run_workflow


def _choices_help(values: set[str]) -> str:
    return ", ".join(sorted(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcl", description="Project Loop Harness CLI")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument("--version", action="version", version=f"pcl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize Project Loop Harness in a target project")
    p_init.add_argument("--target", default=None, help="Target project root. Overrides --root.")
    p_init.add_argument("--force", action="store_true", help="Overwrite template files where safe")
    p_init.add_argument("--no-claude", action="store_true", help="Do not create/update CLAUDE.md")
    p_init.add_argument("--dry-run", action="store_true", help="Inspect the init plan without writing files")

    p_doctor = sub.add_parser("doctor", help="Check project-loop installation health")
    p_doctor.add_argument("--strict", action="store_true")
    p_doctor.add_argument(
        "--check-updates",
        action="store_true",
        help="Also check PyPI for a newer project-loop-harness release.",
    )

    p_validate = sub.add_parser("validate", help="Validate project-loop state")
    p_validate.add_argument("--strict", action="store_true")

    p_migrate = sub.add_parser("migrate", help="Apply or inspect database migrations")
    p_migrate.add_argument(
        "migrate_action",
        nargs="?",
        choices=["apply", "status"],
        default="apply",
        help="Use `status` to inspect migrations without applying them.",
    )
    p_migrate.add_argument("--status", action="store_true", dest="migrate_status", help="Inspect migrations without applying them.")

    p_render = sub.add_parser("render", help="Render dashboard from state")
    p_render.add_argument("--locale", default=None, help="Dashboard HTML locale: en, ja")

    p_update = sub.add_parser("update", help="Check for newer pcl releases")
    update_sub = p_update.add_subparsers(dest="update_command", required=True)
    p_update_check = update_sub.add_parser("check", help="Check PyPI for a newer release")
    p_update_check.add_argument("--no-cache", action="store_true", help="Bypass the local 24h cache")
    p_update_check.add_argument(
        "--timeout",
        type=float,
        default=update_check.DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds.",
    )
    update_sub.add_parser("command", help="Print the recommended manual upgrade command")

    p_goal = sub.add_parser("goal", help="Manage goals")
    goal_sub = p_goal.add_subparsers(dest="goal_command", required=True)
    p_goal_create = goal_sub.add_parser("create")
    p_goal_create.add_argument("--title", required=True)
    p_goal_create.add_argument("--completion-json", default="{}")
    p_goal_create.add_argument("--budget-json", default="{}")
    p_goal_close = goal_sub.add_parser("close")
    p_goal_close.add_argument("goal_id")
    p_goal_close.add_argument("--summary", required=True)
    p_goal_close.add_argument("--evidence", default="")
    p_goal_close.add_argument("--verification", default=None)
    p_goal_cancel = goal_sub.add_parser("cancel")
    p_goal_cancel.add_argument("goal_id")
    p_goal_cancel.add_argument("--summary", required=True)

    p_feature = sub.add_parser("feature", help="Manage features")
    feature_sub = p_feature.add_subparsers(dest="feature_command", required=True)
    p_feature_add = feature_sub.add_parser("add")
    p_feature_add.add_argument("--name", required=True)
    p_feature_add.add_argument("--surface", required=True)
    p_feature_add.add_argument("--description", default="")
    p_feature_add.add_argument("--evidence", default="")
    p_feature_list = feature_sub.add_parser("list")
    p_feature_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by feature status: {_choices_help(FEATURE_STATUSES)}",
    )
    p_feature_read = feature_sub.add_parser("read")
    p_feature_read.add_argument("feature_id")
    p_feature_status = feature_sub.add_parser("status")
    p_feature_status.add_argument("feature_id")
    p_feature_status.add_argument(
        "--status",
        default="",
        help=f"Target feature status: {_choices_help(FEATURE_STATUSES)}",
    )
    p_feature_status.add_argument("--summary", default="")
    p_feature_status.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as command output, artifact path, screenshot path, commit, or report path.",
    )

    p_story = sub.add_parser("story", help="Manage user stories")
    story_sub = p_story.add_subparsers(dest="story_command", required=True)
    p_story_draft = story_sub.add_parser("draft")
    p_story_draft.add_argument("--feature", required=True)
    p_story_draft.add_argument("--actor", required=True)
    p_story_draft.add_argument("--goal", required=True)
    p_story_draft.add_argument("--benefit", default="")
    p_story_draft.add_argument("--expected-behavior", required=True)
    p_story_review = story_sub.add_parser("review")
    p_story_review.add_argument("story_id")
    p_story_review.add_argument("--summary", required=True)
    p_story_approve = story_sub.add_parser("approve")
    p_story_approve.add_argument("story_id")
    p_story_approve.add_argument("--summary", required=True)
    p_story_waive = story_sub.add_parser("waive")
    p_story_waive.add_argument("story_id")
    p_story_waive.add_argument("--reason", required=True)
    p_story_list = story_sub.add_parser("list")
    p_story_list.add_argument("--feature", default=None)
    p_story_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by story status: {_choices_help(STORY_STATUSES)}",
    )
    p_story_read = story_sub.add_parser("read")
    p_story_read.add_argument("story_id")

    p_test = sub.add_parser("test", help="Manage test cases")
    test_sub = p_test.add_subparsers(dest="test_command", required=True)
    p_test_plan = test_sub.add_parser("plan")
    p_test_plan.add_argument("--feature", required=True)
    p_test_plan.add_argument("--story", default=None)
    p_test_plan.add_argument(
        "--type",
        required=True,
        help=f"Test case type: {_choices_help(TEST_CASE_TYPES)}",
    )
    p_test_plan.add_argument("--scenario", required=True)
    p_test_plan.add_argument("--expected", required=True)
    p_test_pass = test_sub.add_parser("pass")
    p_test_pass.add_argument("test_case_id")
    p_test_pass.add_argument("--summary", required=True)
    p_test_pass.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as command output, artifact path, screenshot path, commit, or report path.",
    )
    p_test_pass.add_argument("--run", default=None)
    p_test_fail = test_sub.add_parser("fail")
    p_test_fail.add_argument("test_case_id")
    p_test_fail.add_argument("--summary", required=True)
    p_test_fail.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as failing command output, artifact path, screenshot path, or report path.",
    )
    p_test_fail.add_argument("--run", default=None)
    p_test_block = test_sub.add_parser("block")
    p_test_block.add_argument("test_case_id")
    p_test_block.add_argument("--summary", required=True)
    p_test_block.add_argument("--run", default=None)
    p_test_missing = test_sub.add_parser("missing")
    p_test_missing.add_argument("test_case_id")
    p_test_missing.add_argument("--summary", required=True)
    p_test_waive = test_sub.add_parser("waive")
    p_test_waive.add_argument("test_case_id")
    p_test_waive.add_argument("--reason", required=True)
    p_test_list = test_sub.add_parser("list")
    p_test_list.add_argument("--feature", default=None)
    p_test_list.add_argument("--story", default=None)
    p_test_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by test case status: {_choices_help(TEST_CASE_STATUSES)}",
    )
    p_test_read = test_sub.add_parser("read")
    p_test_read.add_argument("test_case_id")

    p_task = sub.add_parser("task", help="Manage tasks")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)
    p_task_create = task_sub.add_parser("create")
    p_task_create.add_argument("--title", required=True)
    p_task_create.add_argument("--description", default="")
    p_task_create.add_argument("--priority", type=int, default=100)
    p_task_create.add_argument("--owner", default="")
    p_task_create.add_argument("--risk", default=None, help=f"Task risk: {_choices_help(TASK_RISKS)}")
    p_task_create.add_argument("--effort", default="")
    p_task_create.add_argument("--goal", default=None)
    p_task_create.add_argument("--feature", default=None)
    p_task_create.add_argument("--defect", default=None)
    p_task_list = task_sub.add_parser("list")
    p_task_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by task status: {_choices_help(TASK_STATUSES)}",
    )
    p_task_list.add_argument("--goal", default=None)
    p_task_list.add_argument("--owner", default=None)
    p_task_read = task_sub.add_parser("read")
    p_task_read.add_argument("task_id")
    p_task_status = task_sub.add_parser("status")
    p_task_status.add_argument("task_id")
    p_task_status.add_argument("new_status", help=f"Target task status: {_choices_help(TASK_STATUSES)}")
    p_task_status.add_argument("--reason", required=True)
    p_task_depend = task_sub.add_parser("depend")
    p_task_depend.add_argument("task_id")
    p_task_depend.add_argument("--on", required=True, dest="depends_on_task_id")
    p_task_undepend = task_sub.add_parser("undepend")
    p_task_undepend.add_argument("task_id")
    p_task_undepend.add_argument("--on", required=True, dest="depends_on_task_id")

    p_defect = sub.add_parser("defect", help="Manage defects")
    defect_sub = p_defect.add_subparsers(dest="defect_command", required=True)
    p_defect_open = defect_sub.add_parser("open")
    p_defect_open.add_argument("--feature", required=True)
    p_defect_open.add_argument("--severity", required=True, choices=["critical", "high", "medium", "low"])
    p_defect_open.add_argument("--expected", required=True)
    p_defect_open.add_argument("--actual", required=True)
    p_defect_open.add_argument("--test", default=None)
    p_defect_open.add_argument("--reproduction", default="")
    p_defect_open.add_argument("--evidence", default="")
    p_defect_triage = defect_sub.add_parser("triage")
    p_defect_triage.add_argument("defect_id")
    p_defect_triage.add_argument("--summary", required=True)
    p_defect_start = defect_sub.add_parser("start")
    p_defect_start.add_argument("defect_id")
    p_defect_start.add_argument("--summary", required=True)
    p_defect_fix = defect_sub.add_parser("fix")
    p_defect_fix.add_argument("defect_id")
    p_defect_fix.add_argument("--summary", required=True)
    p_defect_fix.add_argument("--evidence", default="")
    p_defect_verify = defect_sub.add_parser("verify")
    p_defect_verify.add_argument("defect_id")
    p_defect_verify.add_argument("--summary", required=True)
    p_defect_verify.add_argument("--verification", required=True)
    p_defect_close = defect_sub.add_parser("close")
    p_defect_close.add_argument("defect_id")
    p_defect_close.add_argument("--summary", required=True)
    p_defect_close.add_argument("--evidence", default="")
    p_defect_waive = defect_sub.add_parser("waive")
    p_defect_waive.add_argument("defect_id")
    p_defect_waive.add_argument("--reason", default="")

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
    p_workflow_propose = workflow_sub.add_parser("propose", help="Store a workflow proposal for review")
    p_workflow_propose.add_argument("--file", required=True, help="Workflow YAML file to propose")
    p_workflow_propose.add_argument("--summary", default="")
    p_workflow_verify = workflow_sub.add_parser("verify", help="Verify a workflow file, proposal, or template")
    workflow_verify_target = p_workflow_verify.add_mutually_exclusive_group(required=True)
    workflow_verify_target.add_argument("--file", default=None, help="Workflow YAML file to verify")
    workflow_verify_target.add_argument("--proposal", default=None, help="Workflow proposal id to verify")
    workflow_verify_target.add_argument("--template", default=None, help="Approved workflow template id to verify")
    p_workflow_guard = workflow_sub.add_parser(
        "guard",
        help="Plan or run allowlisted commands on the host (no OS/network/filesystem isolation)",
    )
    workflow_guard_target = p_workflow_guard.add_mutually_exclusive_group(required=True)
    workflow_guard_target.add_argument("--file", default=None, help="Workflow YAML file to inspect")
    workflow_guard_target.add_argument("--proposal", default=None, help="Workflow proposal id to inspect")
    workflow_guard_target.add_argument("--template", default=None, help="Approved workflow template id")
    p_workflow_guard.add_argument("--execute", action="store_true", help="Run guarded allowlisted commands")
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
    workflow_sandbox_target.add_argument("--file", default=None, help="Workflow YAML file to inspect")
    workflow_sandbox_target.add_argument("--proposal", default=None, help="Workflow proposal id to inspect")
    workflow_sandbox_target.add_argument("--template", default=None, help="Approved workflow template id")
    p_workflow_sandbox.add_argument("--execute", action="store_true", help="Run guarded allowlisted commands")
    p_workflow_sandbox.add_argument("--timeout-seconds", type=int, default=120)
    p_workflow_sandbox.add_argument("--max-output-bytes", type=int, default=1_048_576)
    p_workflow_sandbox.add_argument("--allow-env", action="append", default=[], metavar="NAME")
    p_workflow_proposals = workflow_sub.add_parser("proposals", help="Inspect workflow proposals")
    proposals_sub = p_workflow_proposals.add_subparsers(dest="workflow_proposals_command", required=True)
    p_workflow_proposals_list = proposals_sub.add_parser("list", help="List workflow proposals")
    p_workflow_proposals_list.add_argument("--status", choices=sorted(PROPOSAL_STATUSES), default=None)
    p_workflow_proposals_read = proposals_sub.add_parser("read", help="Read a workflow proposal")
    p_workflow_proposals_read.add_argument("proposal_id")
    p_workflow_proposals_approve = proposals_sub.add_parser("approve", help="Approve a workflow proposal")
    p_workflow_proposals_approve.add_argument("proposal_id")
    p_workflow_proposals_approve.add_argument("--summary", required=True)
    p_workflow_proposals_cancel = proposals_sub.add_parser("cancel", help="Cancel a workflow proposal")
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
    p_jobs_complete.add_argument("--evidence", default=None, help="Existing evidence ID to link to this completion")
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
    p_jobs_release = jobs_sub.add_parser("release", help="Release a running job lease back to queued")
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

    p_evidence = sub.add_parser("evidence", help="Record standalone evidence artifacts")
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

    p_context = sub.add_parser("context", help="Build focused machine context packages")
    context_sub = p_context.add_subparsers(dest="context_command", required=True)
    p_context_pack = context_sub.add_parser("pack", help="Build a focused context pack for an agent job or task")
    context_pack_target = p_context_pack.add_mutually_exclusive_group(required=True)
    context_pack_target.add_argument("--job", dest="job_id", default=None, help="Agent job id to package")
    context_pack_target.add_argument("--task", dest="task_id", default=None, help="Task id to package")
    p_context_pack.add_argument("--role", default=None, help="Reader role for this handoff")
    p_context_pack.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Approximate token budget for the generated Markdown package.",
    )
    p_context_pack.add_argument(
        "--include-code-context",
        action="store_true",
        help="Include the latest code context receipt summary when available.",
    )
    p_context_pack.add_argument(
        "--require-bound-receipt",
        action="store_true",
        help="Require a code-context receipt explicitly bound to the requested job or task.",
    )
    p_context_check = context_sub.add_parser("check", help="Check target-bound context facts")
    context_check_target = p_context_check.add_mutually_exclusive_group(required=True)
    context_check_target.add_argument("--job", dest="job_id", default=None, help="Agent job id to check")
    context_check_target.add_argument("--task", dest="task_id", default=None, help="Task id to check")
    p_context_check.add_argument(
        "--require-bound-receipt",
        action="store_true",
        help="Exit with a typed error unless a matching target-bound code-context receipt is present.",
    )

    p_receipt = sub.add_parser("receipt", help="Inspect code context receipts")
    receipt_sub = p_receipt.add_subparsers(dest="receipt_command", required=True)
    p_receipt_show = receipt_sub.add_parser("show", help="Render a context receipt summary")
    p_receipt_show.add_argument("ref", nargs="?", help="Context receipt evidence id or receipt path")
    p_receipt_show.add_argument(
        "--latest",
        action="store_true",
        help="Show the most recent context_receipt evidence row.",
    )

    p_index = sub.add_parser("index", help="Build and inspect the code context index")
    index_sub = p_index.add_subparsers(dest="index_command", required=True)
    p_index_build = index_sub.add_parser("build", help="Build a gitignore-aware code index snapshot")
    p_index_build.add_argument(
        "--include-files",
        action="store_true",
        help="Inline full per-file index detail in JSON output instead of the default summary.",
    )
    p_index_status = index_sub.add_parser("status", help="Inspect the latest code index snapshot")
    p_index_status.add_argument(
        "--include-files",
        action="store_true",
        help="Inline full per-file index detail in JSON output instead of the default summary.",
    )

    p_code = sub.add_parser("code", help="Search indexed code context")
    code_sub = p_code.add_subparsers(dest="code_command", required=True)
    p_code_search = code_sub.add_parser("search", help="Run a lexical search over indexed files")
    p_code_search.add_argument("query")
    p_code_search.add_argument("--limit", type=int, default=50)

    p_impact = sub.add_parser("impact", help="Explain likely code impact from a diff")
    p_impact.add_argument(
        "--diff",
        dest="diff_source",
        nargs="?",
        const=GIT_DIFF_SENTINEL,
        required=True,
        help=(
            "Diff file to analyze, '-' for stdin, or omit the value to compare "
            "the working tree against HEAD."
        ),
    )
    p_impact.add_argument(
        "--base",
        dest="base_ref",
        default=None,
        help="Compare the working tree against this git ref when --diff has no explicit source.",
    )
    p_impact.add_argument(
        "--staged",
        action="store_true",
        help="Compare staged index changes against HEAD, or against --base when supplied.",
    )
    p_impact.add_argument(
        "--unstaged",
        action="store_true",
        help="Compare unstaged working-tree changes against the index.",
    )
    p_impact.add_argument(
        "--include-untracked",
        action="store_true",
        help="Include untracked, non-gitignored files in git-based diff modes.",
    )
    p_impact.add_argument(
        "--all-changes",
        action="store_true",
        help="Compare all uncommitted tracked changes against HEAD and include untracked files.",
    )
    p_impact.add_argument(
        "--for-task",
        dest="for_task",
        default=None,
        help="Bind the written context receipt to an existing task id as a caller assertion.",
    )
    p_impact.add_argument(
        "--for-job",
        dest="for_job",
        default=None,
        help="Bind the written context receipt to an existing agent job id as a caller assertion.",
    )

    p_eval = sub.add_parser("eval", help="Evaluate retrieval fixtures")
    eval_sub = p_eval.add_subparsers(dest="eval_command", required=True)
    p_eval_retrieval = eval_sub.add_parser("retrieval", help="Evaluate indexed retrieval")
    p_eval_retrieval.add_argument("--fixture", required=True)
    eval_retrieval_baseline = p_eval_retrieval.add_mutually_exclusive_group()
    eval_retrieval_baseline.add_argument(
        "--record-baseline",
        action="store_true",
        help="Store the retrieval eval payload as a provenance-bearing evidence baseline.",
    )
    eval_retrieval_baseline.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare against the latest recorded baseline with the same fixture hash.",
    )
    p_eval_fixture = eval_sub.add_parser("fixture", help="Manage retrieval fixture candidates")
    eval_fixture_sub = p_eval_fixture.add_subparsers(dest="eval_fixture_command", required=True)
    p_eval_fixture_propose = eval_fixture_sub.add_parser(
        "propose",
        help="Propose an unlabeled retrieval fixture from a context receipt.",
    )
    p_eval_fixture_propose.add_argument(
        "--from-receipt",
        required=True,
        dest="from_receipt",
        help="Context receipt evidence ID to stage as an unlabeled fixture candidate.",
    )
    p_eval_fixture_propose.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing proposed candidate after confirming no human labels will be lost.",
    )

    p_verification = sub.add_parser("verification", help="Record verification results")
    verification_sub = p_verification.add_subparsers(dest="verification_command", required=True)
    p_verification_record = verification_sub.add_parser("record")
    p_verification_record.add_argument("--run", required=True)
    p_verification_record.add_argument("--target-job", default=None)
    p_verification_record.add_argument(
        "--result",
        required=True,
        choices=["approved", "rejected", "needs_human", "inconclusive"],
    )
    p_verification_record.add_argument("--verifier-role", default="human")
    rubric_source = p_verification_record.add_mutually_exclusive_group()
    rubric_source.add_argument("--rubric-json", default=None)
    rubric_source.add_argument("--rubric-file", default=None, help="Read verification rubric JSON from a file")
    p_verification_record.add_argument("--reason", action="append", required=True)
    p_verification_list = verification_sub.add_parser("list")
    p_verification_list.add_argument("--run", default=None, help="Filter by workflow run id")
    p_verification_list.add_argument(
        "--result",
        choices=sorted(VERIFICATION_RESULTS),
        default=None,
        help=f"Filter by verification result: {_choices_help(VERIFICATION_RESULTS)}",
    )
    p_verification_read = verification_sub.add_parser("read")
    p_verification_read.add_argument("verification_id")
    p_verification_feedback = verification_sub.add_parser(
        "feedback",
        help="Record a caller claim about a receipt suggestion.",
        epilog=(
            "Example: pcl verification feedback --suggestion 'E-0001/VS-01' "
            "--status executed --result passed --evidence E-0009"
        ),
    )
    p_verification_feedback.add_argument(
        "--suggestion",
        required=True,
        help="Quoted suggestion ID from a context receipt, for example 'E-0001/VS-01'.",
    )
    p_verification_feedback.add_argument(
        "--status",
        required=True,
        help="Caller claim status: executed, skipped, or not_applicable.",
    )
    p_verification_feedback.add_argument(
        "--result",
        default=None,
        help="Caller-stated result for executed feedback: passed, failed, or inconclusive.",
    )
    p_verification_feedback.add_argument(
        "--evidence",
        default=None,
        help="Evidence ID backing the caller claim; required for executed feedback.",
    )
    p_verification_feedback.add_argument("--note", default=None)
    verification_sub.add_parser("stats", help="Read feedback rates for receipt suggestions.")

    p_decision = sub.add_parser("decision", help="Manage human decisions")
    decision_sub = p_decision.add_subparsers(dest="decision_command", required=True)
    p_decision_open = decision_sub.add_parser("open")
    p_decision_open.add_argument("--question", required=True)
    p_decision_open.add_argument("--recommendation", required=True)
    p_decision_open.add_argument("--blocks-json", default="[]")
    p_decision_open.add_argument("--escalation", default=None)
    p_decision_resolve = decision_sub.add_parser("resolve")
    p_decision_resolve.add_argument("decision_id")
    p_decision_resolve.add_argument("--selected-option", required=True)
    p_decision_resolve.add_argument("--reason", required=True)
    p_decision_waive = decision_sub.add_parser("waive")
    p_decision_waive.add_argument("decision_id")
    p_decision_waive.add_argument("--reason", required=True)
    p_decision_list = decision_sub.add_parser("list")
    p_decision_list.add_argument("--status", choices=["open", "resolved", "waived"], default=None)
    p_decision_read = decision_sub.add_parser("read")
    p_decision_read.add_argument("decision_id")

    p_escalation = sub.add_parser("escalation", help="Manage human escalations")
    escalation_sub = p_escalation.add_subparsers(dest="escalation_command", required=True)
    p_escalation_open = escalation_sub.add_parser("open")
    p_escalation_open.add_argument("--severity", required=True, choices=["critical", "high", "medium", "low"])
    p_escalation_open.add_argument("--question", required=True)
    p_escalation_open.add_argument("--recommendation", default="")
    p_escalation_open.add_argument("--run", default=None)
    p_escalation_resolve = escalation_sub.add_parser("resolve")
    p_escalation_resolve.add_argument("escalation_id")
    p_escalation_resolve.add_argument("--summary", required=True)
    p_escalation_resolve.add_argument("--decision", default=None)
    p_escalation_cancel = escalation_sub.add_parser("cancel")
    p_escalation_cancel.add_argument("escalation_id")
    p_escalation_cancel.add_argument("--summary", required=True)
    p_escalation_list = escalation_sub.add_parser("list")
    p_escalation_list.add_argument("--status", choices=["open", "resolved", "cancelled"], default=None)
    p_escalation_read = escalation_sub.add_parser("read")
    p_escalation_read.add_argument("escalation_id")

    p_checkpoint = sub.add_parser("checkpoint", help="Record and inspect integration checkpoints")
    checkpoint_sub = p_checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_sub.add_parser("status", help="Inspect checkpoint recommendation state")
    p_checkpoint_record = checkpoint_sub.add_parser("record", help="Record a human integration checkpoint")
    p_checkpoint_record.add_argument("--summary", required=True)
    p_checkpoint_record.add_argument("--evidence", required=True)
    p_checkpoint_record.add_argument("--review-type", default="integration")

    p_next = sub.add_parser("next", help="Suggest the next harness action")
    p_next.add_argument("--strict", action="store_true", help="Route strict validation failures before normal next actions")
    p_next.add_argument("--explain", action="store_true", help="Print a human-readable explanation of the next action")

    p_finish = sub.add_parser("finish", help="Plan terminal loop close-out steps")
    p_finish.add_argument("--execute", action="store_true", help="Run validate/render only when no finish steps remain")
    p_finish.add_argument("--run", default=None, help="Target a workflow run explicitly")
    p_finish.add_argument("--goal", default=None, help="Target a goal explicitly")

    p_export = sub.add_parser("export", help="Export state")
    export_sub = p_export.add_subparsers(dest="export_command", required=True)
    export_sub.add_parser("csv")

    p_report = sub.add_parser("report", help="Generate evidence reports")
    report_sub = p_report.add_subparsers(dest="report_command", required=True)
    p_report_goal = report_sub.add_parser("goal")
    p_report_goal.add_argument("goal_id")
    p_report_run = report_sub.add_parser("run")
    p_report_run.add_argument("workflow_run_id")
    p_report_feature = report_sub.add_parser("feature")
    p_report_feature.add_argument("feature_id")
    p_report_defect = report_sub.add_parser("defect")
    p_report_defect.add_argument("defect_id")
    p_report_validation = report_sub.add_parser("validation")
    p_report_validation.add_argument("--strict", action="store_true")

    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _impact_text_payload(impact: dict) -> tuple[dict, str | None]:
    display = dict(impact)
    excluded = display.pop("excluded_changed_files", [])
    display["excluded_changed_file_count"] = len(excluded)
    if not excluded:
        return display, None
    paths = [str(item.get("path", "")) for item in excluded if item.get("path")]
    visible = ", ".join(paths[:5])
    if len(paths) > 5:
        visible += f", ... (+{len(paths) - 5} more)"
    return display, f"Excluded changed files: {len(excluded)} ({visible})"


def _print_context_check_summary(payload: dict) -> None:
    target = payload["target"]
    bound = payload["target_bound_code_context"]
    print(f"Context check: {target['type']} {target['id']}")
    print(f"Target-bound code context: {bound['status']}")
    receipt_ref = bound.get("receipt_ref")
    if isinstance(receipt_ref, dict):
        print(f"Receipt: {receipt_ref.get('evidence_id', '')} ({receipt_ref.get('created_at', '')})")
    print(f"Supporting evidence: {payload['supporting_evidence_count']}")
    print(f"Canonical pack command: {payload['canonical_context_pack_command']}")
    refresh_command = payload.get("recommended_refresh_command")
    if refresh_command:
        print(f"Recommended refresh command: {refresh_command}")
    for warning in payload.get("warnings", []):
        print(f"WARNING: {warning}")


def _format_next_explanation(action: dict) -> str:
    lines = [
        f"Next action: {action.get('type', '')}",
        f"Priority: {action.get('priority', '')}",
        f"Blocking: {_yes_no(bool(action.get('blocking')))}",
        f"Requires human: {_yes_no(bool(action.get('requires_human')))}",
        f"Safe to run: {_yes_no(bool(action.get('safe_to_run')))}",
        f"Run policy: {action.get('run_policy', '')}",
        f"Human guidance: {action.get('human_guidance', '')}",
        f"Reason: {action.get('reason', '')}",
        f"Command: {action.get('command', '')}",
        f"Expected after: {action.get('expected_after', '')}",
    ]
    target = action.get("target")
    if isinstance(target, dict) and target.get("id"):
        lines.append(f"Target: {target['id']}")
    return "\n".join(lines)


def _format_finish_summary(payload: dict) -> str:
    target = payload["target"]
    lines = [
        f"Finish target: run={target['run'] or '-'} goal={target['goal'] or '-'}",
        f"Finished: {_yes_no(bool(payload['finished']))}",
    ]
    steps = payload["remaining_steps"]
    if steps:
        lines.append("Remaining steps:")
        for index, step in enumerate(steps, start=1):
            lines.append(
                f"{index}. {step['command']} "
                f"(requires_human={_yes_no(bool(step['requires_human']))}, "
                f"safe_to_run={_yes_no(bool(step['safe_to_run']))})"
            )
    else:
        lines.append("Remaining steps: none")
    if "executed" in payload:
        executed = payload["executed"]
        if executed:
            lines.append("Executed:")
            for item in executed:
                lines.append(f"- {item['command']}: {'ok' if item['ok'] else 'failed'}")
        else:
            lines.append("Executed: none")
        lines.append(f"Changed: {_yes_no(bool(payload['changed']))}")
    return "\n".join(lines)


def _run_finish_tail(paths) -> list[dict]:
    executed: list[dict] = []
    strict = validate_project(paths, strict=True)
    executed.append({"command": "pcl validate --strict", "ok": strict.ok})
    if not strict.ok:
        return executed

    render_validation = validate_project(paths)
    if not render_validation.ok:
        executed.append({"command": "pcl render", "ok": False})
        return executed

    render_dashboard(paths)
    executed.append({"command": "pcl render", "ok": True})
    return executed


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _print_validation(result, *, json_output: bool = False) -> int:
    if json_output:
        _print_json(result.to_dict())
        return 0 if result.ok else 1

    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}")
    if result.ok:
        print("OK")
        return 0
    return 1


def _print_doctor(result, *, update_result=None, json_output: bool = False) -> int:
    if update_result is not None:
        if update_result.update_available and update_result.latest_version:
            result.add_warning(
                f"pcl {update_result.latest_version} is available; "
                f"run `{update_result.install.command}`."
            )
        elif not update_result.ok and not update_result.disabled:
            result.add_warning(f"Could not check for pcl updates: {update_result.error}")

    if json_output:
        payload = result.to_dict()
        if update_result is not None:
            payload["update"] = update_result.to_dict()
        _print_json(payload)
        return 0 if result.ok else 1

    exit_code = _print_validation(result, json_output=False)
    if update_result is not None and result.ok:
        if update_result.disabled:
            print(f"Update check disabled by {update_check.NO_VERSION_CHECK_ENV}.")
        elif update_result.ok and not update_result.update_available:
            print(f"Update check: pcl is up to date ({update_result.current_version})")
    return exit_code


def _print_update_check(result, *, json_output: bool = False) -> int:
    if json_output:
        _print_json(result.to_dict())
        return 0
    if result.disabled:
        print(f"Update check disabled by {update_check.NO_VERSION_CHECK_ENV}.")
    elif not result.ok:
        print(f"Update check unavailable: {result.error}")
    elif result.update_available and result.latest_version:
        print(f"Update available: pcl {result.latest_version} (current {result.current_version})")
        print(f"Run: {result.install.command}")
    else:
        print(f"pcl is up to date ({result.current_version})")
    return 0


def _print_update_command(context, *, json_output: bool = False) -> int:
    payload = {"install": context.to_dict(), "ok": True}
    if json_output:
        _print_json(payload)
    else:
        print(context.command)
    return 0


def _print_init_plan(plan, *, json_output: bool = False) -> int:
    if json_output:
        _print_json(plan.to_dict())
        return 0 if plan.ok else 1
    print(f"Init plan for {plan.root}")
    for entry in plan.changes:
        print(f"[{entry.action.upper():9}] {entry.path}  ({entry.reason})")
    for error in plan.errors:
        print(f"ERROR: {error}")
    print("No files were changed.")
    return 0 if plan.ok else 1


def _print_error(error: PclError, *, json_output: bool = False) -> None:
    if json_output:
        _print_json(error.to_dict())
        return
    print(f"ERROR: {error}", file=sys.stderr)
    allowed = error.details.get("allowed")
    if isinstance(allowed, list) and all(isinstance(value, str) for value in allowed):
        print(f"Allowed values: {', '.join(allowed)}", file=sys.stderr)
    detail_errors = error.details.get("errors")
    if isinstance(detail_errors, list):
        for detail in detail_errors:
            print(f"ERROR: {detail}", file=sys.stderr)
    detail_warnings = error.details.get("warnings")
    if isinstance(detail_warnings, list):
        for detail in detail_warnings:
            print(f"WARNING: {detail}", file=sys.stderr)


def _rubric_json_argument(args) -> str:
    if getattr(args, "rubric_file", None):
        rubric_path = Path(args.rubric_file)
        try:
            return rubric_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidInputError(
                f"Could not read rubric file: {args.rubric_file}",
                details={"path": args.rubric_file},
            ) from exc
    rubric_json = getattr(args, "rubric_json", None)
    return "{}" if rubric_json is None else rubric_json


def _extract_global_options(argv: list[str] | None) -> tuple[list[str] | None, str | None, bool]:
    """Allow global options before or after subcommands for agent-friendliness.

    argparse normally requires global options before the subcommand. Coding agents
    often place --root/--json at the end, so we normalize them here.
    """
    if argv is None:
        argv = sys.argv[1:]
    normalized: list[str] = []
    root_override: str | None = None
    json_output = False
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--root" and i + 1 < len(argv):
            root_override = argv[i + 1]
            i += 2
            continue
        if token.startswith("--root="):
            root_override = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--json":
            json_output = True
            i += 1
            continue
        normalized.append(token)
        i += 1
    return normalized, root_override, json_output


def main(argv: list[str] | None = None) -> int:
    argv, root_override, json_override = _extract_global_options(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    root = getattr(args, "target", None) or root_override or args.root
    paths = resolve_paths(root)
    json_output = json_override or args.json

    try:
        if args.command == "init":
            if args.dry_run:
                plan = plan_init_project(paths, overwrite=args.force, with_claude=not args.no_claude)
                return _print_init_plan(plan, json_output=json_output)
            result = init_project(paths, overwrite=args.force, with_claude=not args.no_claude)
            if json_output:
                _print_json(
                    {
                        "ok": True,
                        "root": str(result.root),
                        "created": result.created,
                        "event_appended": result.event_appended,
                    }
                )
            else:
                print(f"Initialized Project Loop Harness at {paths.root}")
            return 0

        if args.command == "doctor":
            result = validate_project(paths, strict=args.strict, include_config_advice=True)
            update_result = None
            if args.check_updates:
                update_result = update_check.check_for_update()
            return _print_doctor(result, update_result=update_result, json_output=json_output)

        if args.command == "validate":
            result = validate_project(paths, strict=args.strict)
            return _print_validation(result, json_output=json_output)

        if args.command == "migrate":
            if args.migrate_status or args.migrate_action == "status":
                status = migration_status(paths)
                payload = {"ok": True, **status.to_dict()}
                if json_output:
                    _print_json(payload)
                else:
                    print(to_pretty_json(payload))
                return 0
            result = apply_migrations(paths)
            if json_output:
                _print_json(result.to_dict())
            elif result.metadata_repair is not None:
                repair = result.metadata_repair
                print(
                    "Repaired metadata.schema_version from "
                    f"{repair['from_schema_version']} to {repair['to_schema_version']}: "
                    f"{repair['reason']}. This was a metadata repair, not a schema migration."
                )
            elif result.applied:
                for migration in result.applied:
                    print(f"Applied migration {migration.id}")
            else:
                print("No pending migrations")
            return 0

        if args.command == "render":
            result = validate_project(paths)
            if not result.ok:
                return _print_validation(result, json_output=json_output)
            render_dashboard(paths, locale=args.locale)
            if json_output:
                _print_json(
                    {
                        "data_path": str(paths.dashboard_data),
                        "ok": True,
                        "path": str(paths.dashboard_html),
                    }
                )
            else:
                print(f"Rendered {paths.dashboard_html}")
            return 0

        if args.command == "update" and args.update_command == "check":
            result = update_check.check_for_update(
                timeout=args.timeout,
                use_cache=not args.no_cache,
            )
            return _print_update_check(result, json_output=json_output)

        if args.command == "update" and args.update_command == "command":
            context = update_check.detect_install_context()
            return _print_update_command(context, json_output=json_output)

        if args.command == "goal" and args.goal_command == "create":
            goal_id = create_goal(
                paths,
                title=args.title,
                completion_json=args.completion_json,
                budget_json=args.budget_json,
            )
            if json_output:
                _print_json({"id": goal_id, "ok": True})
            else:
                print(goal_id)
            return 0

        if args.command == "goal" and args.goal_command == "close":
            result = close_goal(
                paths,
                goal_id=args.goal_id,
                summary=args.summary,
                evidence=args.evidence,
                verification_id=args.verification,
            )
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Goal {result['goal_id']} already {result['status']}; no change recorded.")
            else:
                print(f"Closed goal {result['goal_id']}")
            return 0

        if args.command == "goal" and args.goal_command == "cancel":
            result = cancel_goal(paths, goal_id=args.goal_id, summary=args.summary)
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Goal {result['goal_id']} already {result['status']}; no change recorded.")
            else:
                print(f"Cancelled goal {result['goal_id']}")
            return 0

        if args.command == "feature" and args.feature_command == "add":
            feature_id = add_feature(
                paths,
                name=args.name,
                surface=args.surface,
                description=args.description,
                evidence=args.evidence,
            )
            if json_output:
                _print_json({"id": feature_id, "ok": True})
            else:
                print(feature_id)
            return 0

        if args.command == "feature" and args.feature_command == "list":
            features = list_features(paths, status=args.status)
            if json_output:
                _print_json({"features": features, "ok": True})
            elif features:
                for feature in features:
                    print(f"{feature['id']} {feature['status']} surface={feature['surface']} name={feature['name']}")
            else:
                print("No features")
            return 0

        if args.command == "feature" and args.feature_command == "read":
            feature = read_feature(paths, args.feature_id)
            if json_output:
                _print_json({"feature": feature, "ok": True})
            else:
                print(to_pretty_json(feature))
            return 0

        if args.command == "feature" and args.feature_command == "status":
            result = set_feature_status(
                paths,
                args.feature_id,
                status=args.status,
                summary=args.summary,
                evidence=args.evidence,
            )
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Feature {result['feature_id']} already {result['status']}; no change recorded.")
            else:
                print(f"Updated feature {result['feature_id']} to {result['status']}")
            return 0

        if args.command == "story" and args.story_command == "draft":
            result = draft_story(
                paths,
                feature_id=args.feature,
                actor=args.actor,
                goal=args.goal,
                benefit=args.benefit,
                expected_behavior=args.expected_behavior,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "story" and args.story_command == "review":
            result = review_story(paths, story_id=args.story_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Reviewed story {result['id']}")
            return 0

        if args.command == "story" and args.story_command == "approve":
            result = approve_story(paths, story_id=args.story_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Approved story {result['id']}")
            return 0

        if args.command == "story" and args.story_command == "waive":
            result = waive_story(paths, story_id=args.story_id, reason=args.reason)
            if json_output:
                _print_json(result)
            else:
                print(f"Waived story {result['id']}")
            return 0

        if args.command == "story" and args.story_command == "list":
            stories = list_stories(paths, feature_id=args.feature, status=args.status)
            if json_output:
                _print_json({"ok": True, "stories": stories})
            elif stories:
                for story in stories:
                    print(f"{story['id']} {story['status']} feature={story['feature_id']} goal={story['goal']}")
            else:
                print("No stories")
            return 0

        if args.command == "story" and args.story_command == "read":
            story = read_story(paths, args.story_id)
            if json_output:
                _print_json({"ok": True, "story": story})
            else:
                print(to_pretty_json(story))
            return 0

        if args.command == "test" and args.test_command == "plan":
            result = plan_test_case(
                paths,
                feature_id=args.feature,
                story_id=args.story,
                test_type=args.type,
                scenario=args.scenario,
                expected=args.expected,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "test" and args.test_command == "pass":
            result = pass_test_case(
                paths,
                test_case_id=args.test_case_id,
                summary=args.summary,
                evidence=args.evidence,
                workflow_run_id=args.run,
            )
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Test case {result['id']} already {result['status']}; no change recorded.")
            else:
                print(f"Passed test case {result['id']}")
            return 0

        if args.command == "test" and args.test_command == "fail":
            result = fail_test_case(
                paths,
                test_case_id=args.test_case_id,
                summary=args.summary,
                evidence=args.evidence,
                workflow_run_id=args.run,
            )
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Test case {result['id']} already {result['status']}; no change recorded.")
            else:
                print(f"Failed test case {result['id']}")
            return 0

        if args.command == "test" and args.test_command == "block":
            result = block_test_case(
                paths,
                test_case_id=args.test_case_id,
                summary=args.summary,
                workflow_run_id=args.run,
            )
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Test case {result['id']} already {result['status']}; no change recorded.")
            else:
                print(f"Blocked test case {result['id']}")
            return 0

        if args.command == "test" and args.test_command == "missing":
            result = missing_test_case(paths, test_case_id=args.test_case_id, summary=args.summary)
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Test case {result['id']} already {result['status']}; no change recorded.")
            else:
                print(f"Marked test case {result['id']} missing")
            return 0

        if args.command == "test" and args.test_command == "waive":
            result = waive_test_case(paths, test_case_id=args.test_case_id, reason=args.reason)
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Test case {result['id']} already {result['status']}; no change recorded.")
            else:
                print(f"Waived test case {result['id']}")
            return 0

        if args.command == "test" and args.test_command == "list":
            test_cases = list_test_cases(
                paths,
                feature_id=args.feature,
                story_id=args.story,
                status=args.status,
            )
            if json_output:
                _print_json({"ok": True, "test_cases": test_cases})
            elif test_cases:
                for test_case in test_cases:
                    print(
                        f"{test_case['id']} {test_case['status']} feature={test_case['feature_id']} "
                        f"type={test_case['type']}"
                    )
            else:
                print("No test cases")
            return 0

        if args.command == "test" and args.test_command == "read":
            test_case = read_test_case(paths, args.test_case_id)
            if json_output:
                _print_json({"ok": True, "test_case": test_case})
            else:
                print(to_pretty_json(test_case))
            return 0

        if args.command == "task" and args.task_command == "create":
            result = create_task(
                paths,
                title=args.title,
                description=args.description,
                priority=args.priority,
                owner=args.owner,
                risk=args.risk,
                effort=args.effort,
                goal_id=args.goal,
                feature_id=args.feature,
                defect_id=args.defect,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "task" and args.task_command == "list":
            tasks = list_tasks(paths, status=args.status, goal_id=args.goal, owner=args.owner)
            if json_output:
                _print_json({"ok": True, "tasks": tasks})
            elif tasks:
                for task in tasks:
                    print(
                        f"{task['id']} {task['status']} priority={task['priority']} "
                        f"title={task['title']}"
                    )
            else:
                print("No tasks")
            return 0

        if args.command == "task" and args.task_command == "read":
            task = read_task(paths, args.task_id)
            if json_output:
                _print_json({"ok": True, "task": task})
            else:
                print(to_pretty_json(task))
            return 0

        if args.command == "task" and args.task_command == "status":
            result = set_task_status(paths, args.task_id, status=args.new_status, reason=args.reason)
            if json_output:
                _print_json(result)
            elif result.get("changed") is False:
                print(f"Task {result['id']} already {result['status']}; no change recorded.")
            else:
                print(f"Updated task {result['id']} from {result['from_status']} to {result['to_status']}")
            return 0

        if args.command == "task" and args.task_command == "depend":
            result = add_dependency(paths, args.task_id, depends_on_task_id=args.depends_on_task_id)
            if json_output:
                _print_json(result)
            else:
                print(f"Added task dependency {result['task_id']} -> {result['depends_on_task_id']}")
            return 0

        if args.command == "task" and args.task_command == "undepend":
            result = remove_dependency(paths, args.task_id, depends_on_task_id=args.depends_on_task_id)
            if json_output:
                _print_json(result)
            else:
                print(f"Removed task dependency {result['task_id']} -> {result['depends_on_task_id']}")
            return 0

        if args.command == "defect" and args.defect_command == "open":
            defect_id = open_defect(
                paths,
                feature_id=args.feature,
                severity=args.severity,
                expected=args.expected,
                actual=args.actual,
                test_case_id=args.test,
                reproduction=args.reproduction,
                evidence=args.evidence,
            )
            if json_output:
                _print_json({"id": defect_id, "ok": True})
            else:
                print(defect_id)
            return 0

        if args.command == "defect" and args.defect_command == "triage":
            result = triage_defect(paths, defect_id=args.defect_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Triaged defect {result['defect_id']}")
            return 0

        if args.command == "defect" and args.defect_command == "start":
            result = start_defect(paths, defect_id=args.defect_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Started defect {result['defect_id']}")
            return 0

        if args.command == "defect" and args.defect_command == "fix":
            result = fix_defect(
                paths,
                defect_id=args.defect_id,
                summary=args.summary,
                evidence=args.evidence,
            )
            if json_output:
                _print_json(result)
            else:
                print(f"Fixed defect {result['defect_id']}")
            return 0

        if args.command == "defect" and args.defect_command == "verify":
            result = verify_defect(
                paths,
                defect_id=args.defect_id,
                summary=args.summary,
                verification_id=args.verification,
            )
            if json_output:
                _print_json(result)
            else:
                print(f"Verified defect {result['defect_id']}")
            return 0

        if args.command == "defect" and args.defect_command == "close":
            result = close_defect(
                paths,
                defect_id=args.defect_id,
                summary=args.summary,
                evidence=args.evidence,
            )
            if json_output:
                _print_json(result)
            else:
                print(f"Closed defect {result['defect_id']}")
            return 0

        if args.command == "defect" and args.defect_command == "waive":
            result = waive_defect(paths, defect_id=args.defect_id, reason=args.reason)
            if json_output:
                _print_json(result)
            else:
                print(f"Waived defect {result['defect_id']}")
            return 0

        if args.command == "loop" and args.loop_command == "status":
            status = loop_status(paths)
            if json_output:
                _print_json(status)
            else:
                print(to_pretty_json(status))
            return 0

        if args.command == "loop" and args.loop_command == "run":
            result = run_workflow(
                paths,
                workflow_id=args.workflow_id,
                goal_id=args.goal,
                defect_id=args.defect,
            )
            if json_output:
                _print_json(result)
            elif result.get("no_op"):
                print(
                    "No workflow run created: all tracked features are already covered "
                    f"({result['covered_feature_count']})."
                )
            else:
                run = result["workflow_run"]
                print(f"Created workflow run {run['id']} for {run['workflow_id']}")
                for job in result["jobs"]:
                    print(f"Queued job {job['id']} role={job['role']} prompt={job['prompt_path']}")
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
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0 if result["ok"] else 1

        if args.command == "loop" and args.loop_command == "complete":
            result = complete_workflow_run(paths, workflow_run_id=args.workflow_run_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Completed workflow run {result['workflow_run_id']}")
            return 0

        if args.command == "loop" and args.loop_command == "fail":
            result = fail_workflow_run(paths, workflow_run_id=args.workflow_run_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Failed workflow run {result['workflow_run_id']}")
            return 0

        if args.command == "loop" and args.loop_command == "cancel":
            result = cancel_workflow_run(paths, workflow_run_id=args.workflow_run_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Cancelled workflow run {result['workflow_run_id']}")
            return 0

        if args.command == "workflow" and args.workflow_command == "propose":
            result = propose_workflow(paths, source_path=args.file, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "workflow" and args.workflow_command == "verify":
            if args.file:
                result = verify_workflow_file(paths, source_path=args.file)
            elif args.proposal:
                result = verify_workflow_proposal(paths, proposal_id=args.proposal)
            else:
                result = verify_workflow_template(paths, workflow_id=args.template)
            payload = {"ok": result["ok"], "verification": result}
            if json_output:
                _print_json(payload)
            else:
                print(to_pretty_json(payload))
            return 0 if result["ok"] else 1

        if args.command == "workflow" and args.workflow_command in {"guard", "sandbox"}:
            legacy_alias = args.workflow_command == "sandbox"
            if legacy_alias:
                print(f"WARNING: {LEGACY_DEPRECATION}", file=sys.stderr)
            file_handler = sandbox_workflow_file if legacy_alias else guard_workflow_file
            proposal_handler = sandbox_workflow_proposal if legacy_alias else guard_workflow_proposal
            template_handler = sandbox_workflow_template if legacy_alias else guard_workflow_template
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
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0 if result["ok"] else 1

        if (
            args.command == "workflow"
            and args.workflow_command == "proposals"
            and args.workflow_proposals_command == "list"
        ):
            proposals = list_workflow_proposals(paths, status=args.status)
            if json_output:
                _print_json({"ok": True, "proposals": proposals})
            elif proposals:
                for proposal in proposals:
                    print(
                        f"{proposal['id']} workflow={proposal['workflow_id']} "
                        f"path={proposal['path']}"
                    )
            else:
                print("No workflow proposals")
            return 0

        if (
            args.command == "workflow"
            and args.workflow_command == "proposals"
            and args.workflow_proposals_command == "read"
        ):
            proposal = read_workflow_proposal(paths, args.proposal_id)
            if json_output:
                _print_json({"ok": True, "proposal": proposal})
            else:
                print(to_pretty_json(proposal))
            return 0

        if (
            args.command == "workflow"
            and args.workflow_command == "proposals"
            and args.workflow_proposals_command == "approve"
        ):
            result = approve_workflow_proposal(paths, args.proposal_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Approved workflow proposal {result['id']} as {result['workflow_path']}")
            return 0

        if (
            args.command == "workflow"
            and args.workflow_command == "proposals"
            and args.workflow_proposals_command == "cancel"
        ):
            result = cancel_workflow_proposal(paths, args.proposal_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Cancelled workflow proposal {result['id']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "list":
            jobs = list_jobs(paths, workflow_run_id=args.run, status=args.status)
            if json_output:
                _print_json({"ok": True, "jobs": jobs})
            elif jobs:
                for job in jobs:
                    print(
                        f"{job['id']} {job['status']} workflow={job['workflow_id']} "
                        f"run={job['workflow_run_id']} role={job['role']}"
                    )
            else:
                print("No agent jobs")
            return 0

        if args.command == "jobs" and args.jobs_command == "read":
            job = read_job(paths, args.job_id)
            if json_output:
                _print_json({"ok": True, "job": job})
            else:
                print(job["prompt"])
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
            if json_output:
                _print_json(result)
            else:
                print(f"Completed job {result['job_id']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "fail":
            result = fail_job(paths, job_id=args.job_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Failed job {result['job_id']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "cancel":
            result = cancel_job(paths, job_id=args.job_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Cancelled job {result['job_id']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "assign":
            result = assign_job(paths, job_id=args.job_id, agent_id=args.agent)
            if json_output:
                _print_json(result)
            else:
                print(f"Assigned job {result['job_id']} to {result['assigned_agent_id']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "lease":
            result = lease_job(
                paths,
                job_id=args.job_id,
                agent_id=args.agent,
                ttl_seconds=args.ttl_seconds,
            )
            if json_output:
                _print_json(result)
            else:
                print(
                    f"Leased job {result['job_id']} to {result['assigned_agent_id']} "
                    f"until {result['lease_expires_at']}"
                )
            return 0

        if args.command == "jobs" and args.jobs_command == "heartbeat":
            result = heartbeat_job(paths, job_id=args.job_id, ttl_seconds=args.ttl_seconds)
            if json_output:
                _print_json(result)
            else:
                print(f"Heartbeat recorded for job {result['job_id']} until {result['lease_expires_at']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "release":
            result = release_job(paths, job_id=args.job_id, reason=args.reason)
            if json_output:
                _print_json(result)
            else:
                print(f"Released job {result['job_id']}")
            return 0

        if args.command == "jobs" and args.jobs_command == "reap":
            result = reap_expired_leases(paths)
            if json_output:
                _print_json(result)
            else:
                print(
                    "Reaped expired leases: "
                    f"requeued={','.join(result['reaped_job_ids']) or '-'} "
                    f"blocked={','.join(result['blocked_job_ids']) or '-'}"
                )
            return 0

        if args.command == "prompt" and args.prompt_command == "job":
            if json_output:
                _print_json(read_job_prompt_handoff(paths, args.job_id))
            else:
                prompt = read_job_prompt(paths, args.job_id)
                print(prompt)
            return 0

        if args.command == "agent" and args.agent_command == "command":
            command = generate_agent_command(paths, args.job_id, args.adapter)
            if json_output:
                _print_json({"ok": True, "agent_command": command.to_dict()})
            else:
                if command.command:
                    print(command.command)
                else:
                    print(command.instructions)
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
            if json_output:
                _print_json(result)
            else:
                print(f"Registered agent {result['id']}")
            return 0

        if args.command == "agent" and args.agent_command == "list":
            agents = list_agents(paths, status=args.status)
            if json_output:
                _print_json({"ok": True, "agents": agents})
            elif agents:
                for agent in agents:
                    print(
                        f"{agent['id']} {agent['status']} name={agent['name']} "
                        f"role={agent['role']} adapter={agent['adapter']} "
                        f"active_leases={agent['active_lease_count']}/{agent['max_concurrency']}"
                    )
            else:
                print("No agents")
            return 0

        if args.command == "agent" and args.agent_command == "read":
            agent = read_agent(paths, args.agent_id)
            if json_output:
                _print_json({"ok": True, "agent": agent})
            else:
                print(to_pretty_json(agent))
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
            if json_output:
                _print_json(result)
            else:
                print(f"Updated agent {result['agent']['id']}")
            return 0

        if args.command == "agent" and args.agent_command == "retire":
            result = retire_agent(paths, args.agent_id, reason=args.reason)
            if json_output:
                _print_json(result)
            else:
                print(f"Retired agent {result['agent']['id']}")
            return 0

        if args.command == "ingest-agent-run":
            result = ingest_agent_run(paths, args.path)
            if json_output:
                _print_json(result)
            else:
                print(
                    f"Ingested {result['output_path']} as {result['evidence_id']} "
                    f"for job {result['job_id']}"
                )
            return 0

        if args.command == "evidence" and args.evidence_command == "add":
            result = record_adhoc_evidence(
                paths,
                files=args.files,
                summary=args.summary,
                command=args.claimed_command,
                allow_sensitive_evidence=args.allow_sensitive_evidence,
                copy_files=args.copy_files,
                task_id=args.task_id,
            )
            if json_output:
                _print_json(result)
            else:
                for warning in result.get("warnings", []):
                    print(f"WARNING: {warning}", file=sys.stderr)
                evidence = result["evidence"]
                print(f"{evidence['id']} {evidence['type']} {evidence['manifest_path']}")
            return 0

        if args.command == "context" and args.context_command == "pack":
            now = utc_now_iso()
            if args.job_id:
                pack = pack_context_for_job(
                    paths,
                    job_id=args.job_id,
                    now=now,
                    reader_role=args.role,
                    max_tokens=args.max_tokens,
                    include_code_context=args.include_code_context,
                    require_bound_receipt=args.require_bound_receipt,
                )
            else:
                pack = pack_context_for_task(
                    paths,
                    task_id=args.task_id,
                    now=now,
                    reader_role=args.role,
                    max_tokens=args.max_tokens,
                    include_code_context=args.include_code_context,
                    require_bound_receipt=args.require_bound_receipt,
                )
            if json_output:
                _print_json({"ok": True, "context_pack": pack})
            else:
                print(pack["markdown"], end="")
            return 0

        if args.command == "context" and args.context_command == "check":
            if args.job_id:
                payload = context_check_for_job(
                    paths,
                    job_id=args.job_id,
                    require_bound_receipt=args.require_bound_receipt,
                )
            else:
                payload = context_check_for_task(
                    paths,
                    task_id=args.task_id,
                    require_bound_receipt=args.require_bound_receipt,
                )
            if json_output:
                _print_json({"ok": True, "context_check": payload})
            else:
                _print_context_check_summary(payload)
            return 0

        if args.command == "receipt" and args.receipt_command == "show":
            summary = receipt_summary_for_ref(
                paths,
                now=utc_now_iso(),
                ref=args.ref,
                latest=args.latest,
            )
            if json_output:
                _print_json(summary)
            else:
                print(render_receipt_summary(summary), end="")
            return 0

        if args.command == "index" and args.index_command == "build":
            result = build_code_index(paths, include_files=args.include_files)
            if json_output:
                _print_json(result)
            else:
                index = result["index"]
                print(
                    f"Indexed {index['file_count']} files "
                    f"({index['indexed_bytes']} bytes), ignored {index['ignored_count']} paths "
                    f"({index['sensitive_omitted_count']} sensitive)"
                )
            return 0

        if args.command == "index" and args.index_command == "status":
            result = code_index_status(paths, include_files=args.include_files)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result["index"]))
            return 0

        if args.command == "code" and args.code_command == "search":
            result = search_code(paths, query=args.query, limit=args.limit)
            if json_output:
                _print_json(result)
            else:
                warning = result["search"].get("git_head_warning")
                if warning:
                    print(warning["message"])
                for item in result["search"]["results"]:
                    lines = item.get("lines") or []
                    line = lines[0] if lines else 0
                    print(f"{item['path']}:{line} {item['snippet']}")
                    if item.get("snapshot_consistency") != "fresh":
                        print(
                            "  warning: "
                            f"snapshot_consistency={item['snapshot_consistency']} "
                            f"({item['snapshot_consistency_reason']})"
                        )
            return 0

        if args.command == "impact":
            result = analyze_impact(
                paths,
                diff_source=args.diff_source,
                base_ref=args.base_ref,
                staged=args.staged,
                unstaged=args.unstaged,
                include_untracked=args.include_untracked,
                all_changes=args.all_changes,
                for_task=args.for_task,
                for_job=args.for_job,
            )
            if json_output:
                _print_json(result)
            else:
                display, excluded_summary = _impact_text_payload(result["impact"])
                print(to_pretty_json(display))
                if excluded_summary:
                    print(excluded_summary)
            return 0

        if args.command == "eval" and args.eval_command == "retrieval":
            if args.record_baseline:
                result = record_retrieval_baseline(paths, fixture_path=args.fixture)
            elif args.compare_baseline:
                result = compare_retrieval_baseline(paths, fixture_path=args.fixture)
            else:
                result = evaluate_retrieval(paths, fixture_path=args.fixture)
            if json_output:
                _print_json(result)
            elif args.record_baseline:
                print(result["baseline"]["evidence_path"])
            elif args.compare_baseline:
                print(to_pretty_json(result["comparison"]))
            else:
                print(to_pretty_json(result["evaluation"]))
            return 0

        if (
            args.command == "eval"
            and args.eval_command == "fixture"
            and args.eval_fixture_command == "propose"
        ):
            result = propose_retrieval_fixture(
                paths,
                receipt_evidence_id=args.from_receipt,
                force=args.force,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["fixture"]["path"])
            return 0

        if args.command == "verification" and args.verification_command == "record":
            result = record_verification(
                paths,
                workflow_run_id=args.run,
                result=args.result,
                reasons=args.reason,
                verifier_role=args.verifier_role,
                rubric_json=_rubric_json_argument(args),
                target_job_id=args.target_job,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "verification" and args.verification_command == "list":
            verifications = list_verifications(paths, workflow_run_id=args.run, result=args.result)
            if json_output:
                _print_json({"ok": True, "verifications": verifications})
            elif verifications:
                for verification in verifications:
                    print(
                        f"{verification['id']} {verification['result']} "
                        f"run={verification['workflow_run_id']} "
                        f"target_job={verification['target_job_id'] or ''}"
                    )
            else:
                print("No verifications")
            return 0

        if args.command == "verification" and args.verification_command == "read":
            verification = read_verification(paths, args.verification_id)
            if json_output:
                _print_json({"ok": True, "verification": verification})
            else:
                print(to_pretty_json(verification))
            return 0

        if args.command == "verification" and args.verification_command == "feedback":
            result = record_verification_feedback(
                paths,
                suggestion_id=args.suggestion,
                status=args.status,
                result=args.result,
                supporting_evidence_id=args.evidence,
                note=args.note,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["feedback"]["id"])
            return 0

        if args.command == "verification" and args.verification_command == "stats":
            result = verification_feedback_stats(paths)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result["stats"]))
            return 0

        if args.command == "decision" and args.decision_command == "open":
            result = open_decision(
                paths,
                question=args.question,
                recommendation=args.recommendation,
                blocks_json=args.blocks_json,
                escalation_id=args.escalation,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "decision" and args.decision_command == "resolve":
            result = resolve_decision(
                paths,
                decision_id=args.decision_id,
                selected_option=args.selected_option,
                reason=args.reason,
            )
            if json_output:
                _print_json(result)
            else:
                print(f"Resolved decision {result['id']}")
            return 0

        if args.command == "decision" and args.decision_command == "waive":
            result = waive_decision(paths, decision_id=args.decision_id, reason=args.reason)
            if json_output:
                _print_json(result)
            else:
                print(f"Waived decision {result['id']}")
            return 0

        if args.command == "decision" and args.decision_command == "list":
            decisions = list_decisions(paths, status=args.status)
            if json_output:
                _print_json({"ok": True, "decisions": decisions})
            elif decisions:
                for decision in decisions:
                    print(f"{decision['id']} {decision['status']} question={decision['question']}")
            else:
                print("No decisions")
            return 0

        if args.command == "decision" and args.decision_command == "read":
            decision = read_decision(paths, args.decision_id)
            if json_output:
                _print_json({"ok": True, "decision": decision})
            else:
                print(to_pretty_json(decision))
            return 0

        if args.command == "escalation" and args.escalation_command == "open":
            result = open_escalation(
                paths,
                severity=args.severity,
                question=args.question,
                recommendation=args.recommendation,
                workflow_run_id=args.run,
            )
            if json_output:
                _print_json(result)
            else:
                print(result["id"])
            return 0

        if args.command == "escalation" and args.escalation_command == "resolve":
            result = resolve_escalation(
                paths,
                escalation_id=args.escalation_id,
                summary=args.summary,
                decision_id=args.decision,
            )
            if json_output:
                _print_json(result)
            else:
                print(f"Resolved escalation {result['id']}")
            return 0

        if args.command == "escalation" and args.escalation_command == "cancel":
            result = cancel_escalation(paths, escalation_id=args.escalation_id, summary=args.summary)
            if json_output:
                _print_json(result)
            else:
                print(f"Cancelled escalation {result['id']}")
            return 0

        if args.command == "escalation" and args.escalation_command == "list":
            escalations = list_escalations(paths, status=args.status)
            if json_output:
                _print_json({"ok": True, "escalations": escalations})
            elif escalations:
                for escalation in escalations:
                    print(
                        f"{escalation['id']} {escalation['status']} severity={escalation['severity']} "
                        f"run={escalation['workflow_run_id'] or ''}"
                    )
            else:
                print("No escalations")
            return 0

        if args.command == "escalation" and args.escalation_command == "read":
            escalation = read_escalation(paths, args.escalation_id)
            if json_output:
                _print_json({"ok": True, "escalation": escalation})
            else:
                print(to_pretty_json(escalation))
            return 0

        if args.command == "checkpoint" and args.checkpoint_command == "status":
            status = checkpoint_status(paths)
            if json_output:
                _print_json(status)
            else:
                print(to_pretty_json(status))
            return 0

        if args.command == "checkpoint" and args.checkpoint_command == "record":
            result = record_checkpoint(
                paths,
                summary=args.summary,
                evidence=args.evidence,
                review_type=args.review_type,
            )
            if json_output:
                _print_json(result)
            else:
                print(f"Recorded checkpoint {result['checkpoint_id']}")
            return 0

        if args.command == "next":
            if args.strict:
                validation = validate_project(paths, strict=True)
                if not validation.ok:
                    action = build_next_action(
                        action_type="resolve_validation_errors",
                        command="pcl report validation --strict",
                        reason="Strict validation failed; review diagnostics before continuing the loop.",
                        target={
                            "strict": True,
                            "ok": validation.ok,
                            "errors": validation.errors,
                            "warnings": validation.warnings,
                        },
                        priority=1,
                        blocking=True,
                        requires_human=True,
                        safe_to_run=True,
                        expected_after="Strict validation passes and normal next-action routing can resume.",
                    )
                else:
                    action = next_action(paths)
            else:
                action = next_action(paths)
            if json_output:
                _print_json(action)
            elif args.explain:
                print(_format_next_explanation(action))
            else:
                print(to_pretty_json(action))
            return 0

        if args.command == "finish":
            payload = finish_plan(paths, run_id=args.run, goal_id=args.goal)
            exit_code = 0
            if args.execute:
                payload = dict(payload)
                if payload["remaining_steps"]:
                    payload["executed"] = []
                    payload["changed"] = False
                else:
                    executed = _run_finish_tail(paths)
                    payload["executed"] = executed
                    payload["changed"] = bool(executed)
                    if any(not item["ok"] for item in executed):
                        exit_code = 1
            if json_output:
                _print_json({"ok": True, "finish": payload})
            else:
                print(_format_finish_summary(payload))
            return exit_code

        if args.command == "export" and args.export_command == "csv":
            paths_written = export_csv(paths)
            if json_output:
                _print_json({"ok": True, "paths": [str(p) for p in paths_written]})
            else:
                for p in paths_written:
                    print(p)
            return 0

        if args.command == "report" and args.report_command == "goal":
            result = report_goal(paths, args.goal_id)
            if json_output:
                _print_json(result)
            else:
                print(result["path"])
            return 0

        if args.command == "report" and args.report_command == "run":
            result = report_run(paths, args.workflow_run_id)
            if json_output:
                _print_json(result)
            else:
                print(result["path"])
            return 0

        if args.command == "report" and args.report_command == "feature":
            result = report_feature(paths, args.feature_id)
            if json_output:
                _print_json(result)
            else:
                print(result["path"])
            return 0

        if args.command == "report" and args.report_command == "defect":
            result = report_defect(paths, args.defect_id)
            if json_output:
                _print_json(result)
            else:
                print(result["path"])
            return 0

        if args.command == "report" and args.report_command == "validation":
            result = report_validation(paths, strict=args.strict)
            if json_output:
                _print_json(result)
            else:
                print(result["path"])
            return 0

        parser.error("Unhandled command")
        return 2
    except PclError as exc:
        _print_error(exc, json_output=json_output)
        return exc.exit_code
    except sqlite3.Error as exc:
        error = DataStoreError(f"SQLite error while running {args.command}: {exc}")
        _print_error(error, json_output=json_output)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
