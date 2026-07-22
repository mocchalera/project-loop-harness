from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .audit import (
    AuditCommandError,
    EXIT_AUDIT_INTERNAL,
    audit_check,
    audit_check_exit_code,
    audit_rebuild_exit_code,
    audit_repair,
    audit_repair_exit_code,
    rebuild_jsonl_from_sqlite,
)
from .adaptive_policy import render_policy_explanation, resolve_policy_for_target
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
    build_next_action,
    finish_plan,
    next_action,
    to_pretty_json,
)
from .context import (
    DEFAULT_MAX_TOKENS,
    context_check_for_job,
    context_check_for_task,
    pack_context_for_job,
    pack_context_for_task,
)
from .context_usage import record_context_pack_usage
from .contracts.completion_packet import (
    COMPLETION_PACKET_CONTRACT_VERSION,
    load_completion_packet,
    validate_completion_packet,
)
from .contracts.handoff_packet import (
    HANDOFF_PACKET_CONTRACT_VERSION,
    load_handoff_packet,
    validate_handoff_packet,
)
from .contracts.intent_index import (
    INTENT_INDEX_CONTRACT_VERSION,
    load_intent_index,
    validate_intent_index,
)
from .contracts.work_brief import (
    WORK_BRIEF_CONTRACT_VERSION,
    load_work_brief,
    validate_work_brief,
)
from .contracts.gap_report import (
    GAP_CLASSES,
    GAP_REPORT_CONTRACT_VERSION,
    load_gap_report,
    validate_gap_report,
)
from .contracts.route_recommendation import (
    ROUTE_RECOMMENDATION_CONTRACT_VERSION,
    load_route_recommendation,
    validate_route_recommendation,
)
from .contracts.route_override import (
    ROUTE_OVERRIDE_CONTRACT_VERSION,
    load_route_override,
    validate_route_override,
)
from .contracts.evidence_set import (
    EVIDENCE_SET_CONTRACT_VERSION,
    load_evidence_set,
    validate_evidence_set,
)
from .contracts.completion_policy import (
    COMPLETION_POLICY_CONTRACT_VERSION,
    load_completion_policy,
    validate_completion_policy,
)
from .contracts.profile_manifest import (
    PROFILE_MANIFEST_CONTRACT_VERSION,
    load_profile_manifest,
    validate_profile_manifest,
)
from .contracts.profile_run_request import (
    PROFILE_RUN_REQUEST_CONTRACT_VERSION,
    load_profile_run_request,
    validate_profile_run_request,
)
from .contracts.profile_output_bundle import (
    PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION,
    load_profile_output_bundle,
    validate_profile_output_bundle,
)
from .contracts.council_run import (
    COUNCIL_RUN_CONTRACT_VERSION,
    load_council_run,
    validate_council_run,
)
from .contracts.claim_set import (
    CLAIM_SET_CONTRACT_VERSION,
    load_claim_set,
    validate_claim_set,
)
from .contracts.verification_plan import (
    VERIFICATION_PLAN_CONTRACT_VERSION,
    load_verification_plan,
    validate_verification_plan,
)
from .contracts.decision_proposal import (
    DECISION_PROPOSAL_CONTRACT_VERSION,
    load_decision_proposal,
    validate_decision_proposal,
)
from .code_context.summary import render_receipt_summary
from .evidence_sets import plan_evidence_set, record_evidence_set, show_evidence_set
from .completion_policies import evaluate_completion_policy
from .errors import DataStoreError, InvalidInputError, PclError
from .entity_handlers import handle_entity_command
from .execution_handlers import handle_execution_command
from .exporters import export_csv
from .finish_execution import emit_finish_packet, plan_finish_packet
from .init_project import init_project, plan_init_project
from .kpi_report import report_kpi
from .skill_usage_report import (
    default_skill_usage_roots,
    render_skill_usage_markdown,
    report_skill_usage,
    serialized_skill_usage_report,
    write_skill_usage_report,
)
from .lifecycle_repair import (
    apply_structural_lifecycle_repair,
    build_lifecycle_repair_plan,
    render_lifecycle_repair_plan,
)
from .migrations import apply_migrations, migration_status
from .outbox import project_pending_events
from .paths import resolve_paths
from .presentation import (
    format_context_check_summary as _format_context_check_summary,
    format_finish_summary as _format_finish_summary,
    format_next_explanation as _format_next_explanation,
    format_start_summary as _format_start_summary,
    impact_text_payload as _impact_text_payload,
)
from .profiles import list_profiles, show_profile, validate_profile
from .profile_ingest import plan_profile_ingest
from .profile_bundle_store import ingest_profile_bundle
from .profile_authorization import (
    ProfileAuthorizationError,
    authorize_profile_request,
    revoke_profile_authorization,
)
from .profile_fixture_runner import run_profile_fixture
from .profile_prepare import prepare_profile_request
from .renderer import render_dashboard
from .receipt_show import receipt_summary_for_ref
from .read_handlers import (
    handle_doctor,
    handle_guide,
    handle_loop_status,
    handle_report_artifact,
)
from .registry import (
    AGENT_STATUSES,
)
from .routing import recommend_route
from .route_overrides import current_route, override_route
from .resume import build_handoff_packet, render_handoff_markdown, serialized_handoff_packet
from .stories import (
    STORY_STATUSES,
    TEST_CASE_STATUSES,
    TEST_CASE_TYPES,
)
from .start import start_work
from .timeutil import utc_now_iso
from .tasks import (
    TASK_RISKS,
    TASK_STATUSES,
)
from . import update_check
from .validators import validate_project
from .verifications import VERIFICATION_RESULTS
from .workflow_proposals import (
    PROPOSAL_STATUSES,
)
from .work_briefs import add_work_brief, approve_work_brief, review_work_brief, show_work_brief
from .gap_reports import add_gap_report, list_gap_reports, promote_gap_lesson, show_gap_report
from .governance_handlers import handle_governance_command


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
    init_write_mode = p_init.add_mutually_exclusive_group()
    init_write_mode.add_argument(
        "--force", action="store_true", help="Overwrite template files where safe"
    )
    init_write_mode.add_argument(
        "--repair-config",
        action="store_true",
        help="Normalize legacy empty command placeholders to null without overwriting pcl.yaml",
    )
    init_write_mode.add_argument(
        "--refresh-skill",
        action="store_true",
        help=(
            "Refresh only the bundled project-control-loop Skill, preserving the replaced "
            "bytes in a hash-addressed backup"
        ),
    )
    p_init.add_argument("--no-claude", action="store_true", help="Do not create/update CLAUDE.md")
    p_init.add_argument(
        "--dry-run", action="store_true", help="Inspect the init plan without writing files"
    )

    p_start = sub.add_parser("start", help="Start one intent as minimal active project work")
    p_start.add_argument(
        "intent", help="Natural-language intent; preserved literally and never executed"
    )
    p_start.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview initialization and state changes without mutation",
    )
    p_start.add_argument(
        "--no-init",
        action="store_true",
        help="Stop instead of initializing an uninitialized project",
    )
    p_start.add_argument(
        "--new",
        action="store_true",
        help="Start separate work even when active work already exists",
    )
    p_start.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Readable Skill file to hash before mutation; repeatable",
    )

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
    p_migrate.add_argument(
        "--status",
        action="store_true",
        dest="migrate_status",
        help="Inspect migrations without applying them.",
    )

    p_audit = sub.add_parser("audit", help="Manage the SQLite-backed audit projection")
    audit_sub = p_audit.add_subparsers(dest="audit_command", required=True)
    audit_sub.add_parser("flush", help="Project eligible committed events to events.jsonl")
    audit_sub.add_parser("check", help="Read-only integrity check for audit and Evidence state")
    p_audit_repair = audit_sub.add_parser(
        "repair",
        help="Preview or apply supported audit repairs; preview is the default",
    )
    repair_mode = p_audit_repair.add_mutually_exclusive_group()
    repair_mode.add_argument("--dry-run", action="store_true", help="Preview without mutation")
    repair_mode.add_argument("--apply", action="store_true", help="Apply the displayed repair plan")
    p_audit_rebuild = audit_sub.add_parser(
        "rebuild-jsonl",
        help="Generate a verified events.jsonl projection from authoritative SQLite events",
    )
    p_audit_rebuild.add_argument(
        "--from-sqlite",
        action="store_true",
        required=True,
        help="Use authoritative SQLite events as the rebuild source",
    )

    p_audit_rebuild.add_argument("--output", default=None, help="Preview output path")
    p_audit_rebuild.add_argument(
        "--apply",
        action="store_true",
        help="Backup and atomically replace events.jsonl, then record an audit event",
    )

    p_repair = sub.add_parser("repair", help="Plan repairs for existing project state")
    repair_sub = p_repair.add_subparsers(dest="repair_command", required=True)
    p_repair_lifecycle = repair_sub.add_parser(
        "lifecycle",
        help="Build a deterministic read-only lifecycle repair plan",
    )
    p_repair_lifecycle.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly select the default read-only planning mode",
    )
    p_repair_lifecycle.add_argument(
        "--apply-structural",
        action="store_true",
        help="Atomically apply only recognized safe structural actions from the current plan",
    )
    p_repair_lifecycle.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)

    p_render = sub.add_parser("render", help="Render dashboard from state")
    p_render.add_argument("--locale", default=None, help="Dashboard HTML locale: en, ja")

    p_update = sub.add_parser("update", help="Check for newer pcl releases")
    update_sub = p_update.add_subparsers(dest="update_command", required=True)
    p_update_check = update_sub.add_parser("check", help="Check PyPI for a newer release")
    p_update_check.add_argument(
        "--no-cache", action="store_true", help="Bypass the local 24h cache"
    )
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
    goal_evidence = p_goal_close.add_mutually_exclusive_group()
    goal_evidence.add_argument("--evidence", default="")
    goal_evidence.add_argument("--evidence-id", default=None)
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
    p_feature_add.add_argument(
        "--task", default=None, help="Atomically link the new Feature to an existing Task"
    )
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
    feature_evidence = p_feature_status.add_mutually_exclusive_group()
    feature_evidence.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as command output, artifact path, screenshot path, commit, or report path.",
    )
    feature_evidence.add_argument("--evidence-id", default=None)

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
    p_test_link = test_sub.add_parser(
        "link", help="Repair Story and Evidence relationships without replaying Test status"
    )
    p_test_link.add_argument("test_case_id")
    p_test_link.add_argument("--story", default=None)
    p_test_link.add_argument("--evidence-id", default=None)
    p_test_link.add_argument("--summary", required=True)
    p_test_pass = test_sub.add_parser("pass")
    p_test_pass.add_argument("test_case_id")
    p_test_pass.add_argument("--summary", required=True)
    test_pass_evidence = p_test_pass.add_mutually_exclusive_group()
    test_pass_evidence.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as command output, artifact path, screenshot path, commit, or report path.",
    )
    test_pass_evidence.add_argument("--evidence-id", default=None)
    p_test_pass.add_argument("--run", default=None)
    p_test_pass.add_argument(
        "--completion-policy",
        default=None,
        dest="completion_policy_file",
        help="completion-policy/v1 JSON required when --evidence-id is an evidence_set receipt.",
    )
    p_test_reverify = test_sub.add_parser(
        "reverify",
        help="Replace proof for a passing Test with an evaluated Evidence Set",
    )
    p_test_reverify.add_argument("test_case_id")
    p_test_reverify.add_argument("--summary", required=True)
    p_test_reverify.add_argument("--evidence-id", required=True)
    p_test_reverify.add_argument(
        "--completion-policy",
        required=True,
        dest="completion_policy_file",
        help="completion-policy/v1 JSON evaluated against the exact target-bound Evidence Set.",
    )
    p_test_fail = test_sub.add_parser("fail")
    p_test_fail.add_argument("test_case_id")
    p_test_fail.add_argument("--summary", required=True)
    test_fail_evidence = p_test_fail.add_mutually_exclusive_group()
    test_fail_evidence.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as failing command output, artifact path, screenshot path, or report path.",
    )
    test_fail_evidence.add_argument("--evidence-id", default=None)
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
    p_task_create.add_argument(
        "--risk", default=None, help=f"Task risk: {_choices_help(TASK_RISKS)}"
    )
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
    p_task_status.add_argument(
        "new_status", help=f"Target task status: {_choices_help(TASK_STATUSES)}"
    )
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
    p_defect_open.add_argument(
        "--severity", required=True, choices=["critical", "high", "medium", "low"]
    )
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

    p_profile = sub.add_parser(
        "profile",
        help=(
            "Inspect built-in external runner Profiles; route_profile and role_profile "
            "are separate concepts"
        ),
        description=(
            "Inspect built-in data-only runner Profiles. runner_profile_id identifies "
            "the external contract; route_profile selects Direct/Discover/Assure; "
            "role_profile selects context packing. No command here executes a runner."
        ),
    )
    profile_sub = p_profile.add_subparsers(dest="profile_command", required=True)
    profile_sub.add_parser(
        "list",
        help="List built-in data-only runner Profile IDs without executing a runner",
    )
    p_profile_show = profile_sub.add_parser(
        "show",
        help="Show one built-in runner Profile manifest without executing it",
    )
    p_profile_show.add_argument(
        "runner_profile_id",
        help="Runner Profile ID, for example council.discovery (not a route_profile)",
    )
    p_profile_validate = profile_sub.add_parser(
        "validate",
        help="Validate one built-in runner Profile and contract compatibility",
    )
    p_profile_validate.add_argument(
        "runner_profile_id",
        help="Runner Profile ID, for example council.discovery (not a role_profile)",
    )
    p_profile_prepare = profile_sub.add_parser(
        "prepare",
        help=(
            "Build a deterministic read-only request from recorded route Evidence; "
            "never execute a runner"
        ),
    )
    p_profile_prepare.add_argument(
        "runner_profile_id",
        help="Runner Profile ID, for example council.discovery",
    )
    p_profile_prepare.add_argument(
        "--target",
        required=True,
        dest="target_ref",
        help="Target reference as task:T-XXXX",
    )
    p_profile_prepare.add_argument(
        "--brief",
        dest="brief_id",
        help="Explicit healthy Work Brief Evidence ID when candidates are ambiguous",
    )
    p_profile_prepare.add_argument(
        "--output",
        default=None,
        help="Write only the generated request JSON to this explicit path",
    )
    p_profile_prepare.add_argument(
        "--network-access",
        choices=["forbidden", "requested"],
        default="forbidden",
    )
    p_profile_prepare.add_argument("--provider", action="append", default=[])
    p_profile_prepare.add_argument("--paid-service", action="store_true")
    p_profile_prepare.add_argument("--monetary-budget", type=float, default=None)
    p_profile_prepare.add_argument("--currency", default=None)
    p_profile_prepare.add_argument(
        "--repository-content-policy",
        choices=["none", "selected_snippets", "full_allowed"],
        default="selected_snippets",
    )
    p_profile_ingest = profile_sub.add_parser(
        "ingest",
        help=(
            "Validate an external Profile bundle and plan mutations; "
            "dry-run never mutates state or executes proposed commands"
        ),
    )
    p_profile_ingest.add_argument(
        "--request",
        required=True,
        dest="request_file",
        help="Prepared profile-run-request/v1 JSON file",
    )
    p_profile_ingest.add_argument(
        "--bundle",
        required=True,
        dest="bundle_file",
        help="External profile-output-bundle/v1 JSON manifest",
    )
    p_profile_ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and return an exact read-only mutation plan",
    )
    p_profile_ingest.add_argument(
        "--accept-failed",
        action="store_true",
        help="Explicitly persist a failed bundle; requires --summary",
    )
    p_profile_ingest.add_argument(
        "--summary",
        help="Human summary required with --accept-failed",
    )
    p_profile_authorize = profile_sub.add_parser(
        "authorize",
        help="Record bounded human authorization for one candidate request; never run a provider",
    )
    p_profile_authorize.add_argument("--request", dest="request_file")
    p_profile_authorize.add_argument("--output")
    p_profile_authorize.add_argument(
        "--revoke",
        dest="authorized_event_id",
        help="Revoke a prior profile_run_authorized event; never run a provider",
    )
    p_profile_authorize.add_argument("--actor", required=True)
    p_profile_authorize.add_argument("--actor-kind", default=None)
    p_profile_authorize.add_argument("--recorded-by", default=None)
    p_profile_authorize.add_argument("--recorder-kind", default=None)
    p_profile_authorize.add_argument(
        "--source-kind",
        required=True,
        choices=["cli", "conversation", "cockpit", "api"],
    )
    p_profile_authorize.add_argument("--source-ref", required=True)
    p_profile_authorize.add_argument("--reason", required=True)
    p_profile_authorize.add_argument("--max-cost", type=float, default=None)
    p_profile_authorize.add_argument("--currency", default=None)
    p_profile_authorize.add_argument("--provider", action="append", default=[])
    p_profile_authorize.add_argument(
        "--data-class",
        action="append",
        default=[],
        choices=["metadata", "selected_snippets", "full_repository"],
    )
    p_profile_authorize.add_argument("--expires-at", default=None)
    p_profile_fixture = profile_sub.add_parser(
        "fixture-run",
        help="Generate deterministic offline Council output without a provider or PLH mutation",
    )
    p_profile_fixture.add_argument("--request", required=True, dest="request_file")
    p_profile_fixture.add_argument(
        "--status",
        required=True,
        choices=[
            "completed",
            "needs_human",
            "partial",
            "budget_exhausted",
            "failed",
            "skipped",
            "malformed",
        ],
    )
    p_profile_fixture.add_argument("--output-dir", required=True)

    p_contract = sub.add_parser("contract", help="Validate versioned artifact contracts")
    contract_sub = p_contract.add_subparsers(dest="contract_command", required=True)
    p_contract_validate = contract_sub.add_parser(
        "validate",
        help="Validate a contract artifact without mutating project state",
    )
    p_contract_validate.add_argument(
        "--type",
        required=True,
        choices=[
            COMPLETION_PACKET_CONTRACT_VERSION,
            HANDOFF_PACKET_CONTRACT_VERSION,
            INTENT_INDEX_CONTRACT_VERSION,
            ROUTE_RECOMMENDATION_CONTRACT_VERSION,
            ROUTE_OVERRIDE_CONTRACT_VERSION,
            WORK_BRIEF_CONTRACT_VERSION,
            GAP_REPORT_CONTRACT_VERSION,
            EVIDENCE_SET_CONTRACT_VERSION,
            COMPLETION_POLICY_CONTRACT_VERSION,
            PROFILE_MANIFEST_CONTRACT_VERSION,
            PROFILE_RUN_REQUEST_CONTRACT_VERSION,
            PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION,
            COUNCIL_RUN_CONTRACT_VERSION,
            CLAIM_SET_CONTRACT_VERSION,
            VERIFICATION_PLAN_CONTRACT_VERSION,
            DECISION_PROPOSAL_CONTRACT_VERSION,
        ],
        dest="contract_type",
    )
    p_contract_validate.add_argument("file", help="Path to the JSON contract artifact")

    p_evidence_set = sub.add_parser(
        "evidence-set",
        help="Plan, record, and inspect target-bound Evidence completeness receipts",
    )
    evidence_set_sub = p_evidence_set.add_subparsers(
        dest="evidence_set_command",
        required=True,
    )
    for command_name in ("plan", "record"):
        parser_item = evidence_set_sub.add_parser(
            command_name,
            help=(
                "Build a read-only evidence-set/v1 plan"
                if command_name == "plan"
                else "Record an immutable evidence-set/v1 Evidence artifact"
            ),
        )
        parser_item.add_argument(
            "--target",
            required=True,
            dest="target_ref",
            help="Target reference as <target-type>:<target-id>",
        )
        parser_item.add_argument(
            "--work-root",
            required=True,
            help="Explicit project-contained work root used for report discovery",
        )
        parser_item.add_argument(
            "--manifest",
            required=True,
            dest="manifest_file",
            help="evidence-report-manifest/v1 JSON inside the work root",
        )
        parser_item.add_argument(
            "--required-kind",
            action="append",
            default=[],
            dest="required_kinds",
            help="Required report kind. Repeat for multiple kinds.",
        )
        parser_item.add_argument(
            "--include",
            action="append",
            default=[],
            dest="included_refs",
            help="Included report mapping as KIND=E-XXXX:ROLE. Repeat as needed.",
        )
        if command_name == "record":
            parser_item.add_argument("--summary", required=True)
    p_evidence_set_show = evidence_set_sub.add_parser(
        "show",
        help="Inspect recorded Evidence set metadata and artifact health",
    )
    p_evidence_set_show.add_argument("--evidence", required=True, dest="evidence_id")

    p_completion = sub.add_parser(
        "completion",
        help="Evaluate domain-neutral completion policies against Evidence sets",
    )
    completion_sub = p_completion.add_subparsers(dest="completion_command", required=True)
    p_completion_evaluate = completion_sub.add_parser(
        "evaluate",
        help="Read-only completion-policy/v1 evaluation",
    )
    p_completion_evaluate.add_argument("--policy", required=True, dest="policy_file")
    p_completion_evaluate.add_argument(
        "--evidence-set",
        required=True,
        dest="evidence_set_id",
    )
    p_completion_evaluate.add_argument("--test", default=None, dest="test_case_id")

    p_brief = sub.add_parser("brief", help="Manage immutable Work Brief Evidence")
    brief_sub = p_brief.add_subparsers(dest="brief_command", required=True)
    p_brief_add = brief_sub.add_parser("add", help="Validate and record a Work Brief")
    p_brief_add.add_argument("file", help="Path to work-brief/v1 JSON")
    p_brief_add.add_argument("--summary", required=True)
    p_brief_add.add_argument("--dry-run", action="store_true")
    p_brief_show = brief_sub.add_parser("show", help="Inspect Work Brief Evidence")
    brief_show_target = p_brief_show.add_mutually_exclusive_group(required=True)
    brief_show_target.add_argument("--evidence", dest="evidence_id")
    brief_show_target.add_argument(
        "--target",
        dest="target_ref",
        help="Target reference as <target-type>:<target-id>",
    )
    p_brief_approve = brief_sub.add_parser(
        "approve",
        help="Approve immutable Work Brief Evidence against its current hash",
    )
    p_brief_approve.add_argument("evidence_id")
    p_brief_approve.add_argument("--actor", required=True)
    p_brief_approve.add_argument("--actor-kind", choices=["human", "agent", "system"])
    p_brief_approve.add_argument(
        "--recorded-by",
        help="Identity that writes the approval to PCL; defaults to --actor for direct CLI approval",
    )
    p_brief_approve.add_argument(
        "--recorder-kind",
        choices=["human", "agent", "system"],
    )
    p_brief_approve.add_argument(
        "--source-kind",
        choices=["cli", "conversation", "cockpit", "api"],
        help="Origin of the human decision; mediated approval requires conversation or cockpit",
    )
    p_brief_approve.add_argument(
        "--source-ref",
        help="Factual reference to the conversation, Cockpit task, or API decision source",
    )
    p_brief_approve.add_argument("--reason", required=True)
    p_brief_approve.add_argument("--dry-run", action="store_true")
    p_brief_review = brief_sub.add_parser(
        "review",
        help="Record a hash-bound human, agent, or system review without approving",
    )
    p_brief_review.add_argument("evidence_id")
    p_brief_review.add_argument("--actor", required=True)
    p_brief_review.add_argument("--actor-kind", choices=["human", "agent", "system"])
    p_brief_review.add_argument("--reason", required=True)
    p_brief_review.add_argument("--dry-run", action="store_true")

    p_gap = sub.add_parser("gap", help="Manage immutable Harness Gap Report Evidence")
    gap_sub = p_gap.add_subparsers(dest="gap_command", required=True)
    p_gap_add = gap_sub.add_parser("add", help="Validate and record a gap-report/v1")
    p_gap_add.add_argument("file", help="Path to gap-report/v1 JSON")
    p_gap_add.add_argument("--summary", required=True)
    p_gap_add.add_argument("--dry-run", action="store_true")
    p_gap_show = gap_sub.add_parser("show", help="Inspect Gap Report Evidence")
    p_gap_show.add_argument("--evidence", required=True, dest="evidence_id")
    p_gap_list = gap_sub.add_parser("list", help="List Gap Report Evidence")
    p_gap_list.add_argument(
        "--target",
        dest="target_ref",
        help="Optional target reference as <target-type>:<target-id>",
    )
    p_gap_list.add_argument("--gap-class", choices=sorted(GAP_CLASSES))
    p_gap_promote = gap_sub.add_parser(
        "promote",
        help="Approve a candidate lesson for later application to its durable owner",
    )
    p_gap_promote.add_argument("evidence_id")
    p_gap_promote.add_argument("--lesson", required=True, dest="lesson_id")
    p_gap_promote.add_argument("--actor", required=True)
    p_gap_promote.add_argument("--actor-kind", choices=["human", "agent", "system"])
    p_gap_promote.add_argument(
        "--recorded-by",
        help="Identity that writes the human decision to PCL; defaults to --actor",
    )
    p_gap_promote.add_argument(
        "--recorder-kind",
        choices=["human", "agent", "system"],
    )
    p_gap_promote.add_argument(
        "--source-kind",
        choices=["cli", "conversation", "cockpit", "api"],
        help="Origin of the human decision; mediated approval requires conversation or cockpit",
    )
    p_gap_promote.add_argument(
        "--source-ref",
        help="Factual reference to the conversation, Cockpit task, or API decision source",
    )
    p_gap_promote.add_argument("--reason", required=True)
    p_gap_promote.add_argument("--dry-run", action="store_true")

    p_route = sub.add_parser("route", help="Recommend deterministic work routes")
    route_sub = p_route.add_subparsers(dest="route_command", required=True)
    p_route_recommend = route_sub.add_parser(
        "recommend",
        help="Resolve a Direct, Discover, or Assure recommendation",
    )
    p_route_recommend.add_argument(
        "--target",
        required=True,
        dest="target_ref",
        help="Target reference as <target-type>:<target-id>",
    )
    p_route_recommend.add_argument(
        "--brief",
        dest="brief_file",
        help="Optional prospective work-brief/v1 JSON; approved target brief is used by default",
    )
    p_route_recommend.add_argument(
        "--changed-path",
        action="append",
        default=[],
        dest="changed_paths",
    )
    p_route_recommend.add_argument(
        "--record",
        action="store_true",
        help="Explicitly persist the recommendation as target-linked Evidence",
    )
    p_route_override = route_sub.add_parser(
        "override",
        help="Preview or record an explicit audited route override",
    )
    p_route_override.add_argument("--target", required=True, dest="target_ref")
    p_route_override.add_argument(
        "--profile",
        required=True,
        choices=["direct", "discover", "assure"],
        dest="requested_profile",
    )
    p_route_override.add_argument("--actor", required=True)
    p_route_override.add_argument("--reason", required=True)
    p_route_override.add_argument("--brief", dest="brief_file")
    p_route_override.add_argument("--policy", dest="policy_file")
    p_route_override.add_argument(
        "--changed-path",
        action="append",
        default=[],
        dest="changed_paths",
    )
    p_route_override.add_argument("--dry-run", action="store_true")
    p_route_current = route_sub.add_parser(
        "current",
        help="Inspect the original and effective current route",
    )
    p_route_current.add_argument("--target", required=True, dest="target_ref")
    p_route_current.add_argument("--brief", dest="brief_file")
    p_route_current.add_argument("--policy", dest="policy_file")
    p_route_current.add_argument(
        "--changed-path",
        action="append",
        default=[],
        dest="changed_paths",
    )

    p_policy = sub.add_parser("policy", help="Resolve and explain adaptive policy")
    policy_sub = p_policy.add_subparsers(dest="policy_command", required=True)
    for policy_command, policy_help in (
        ("resolve", "Resolve deterministic multi-axis policy"),
        ("explain", "Explain each resolved policy axis"),
    ):
        p_policy_action = policy_sub.add_parser(policy_command, help=policy_help)
        p_policy_action.add_argument(
            "--target",
            required=True,
            dest="target_ref",
            help="Target reference as <target-type>:<target-id>",
        )
        p_policy_action.add_argument("--brief", dest="brief_file")
        p_policy_action.add_argument("--policy", dest="policy_file")
        p_policy_action.add_argument(
            "--changed-path",
            action="append",
            default=[],
            dest="changed_paths",
        )

    p_context = sub.add_parser("context", help="Build focused machine context packages")
    context_sub = p_context.add_subparsers(dest="context_command", required=True)
    p_context_pack = context_sub.add_parser(
        "pack", help="Build a focused context pack for an agent job or task"
    )
    context_pack_target = p_context_pack.add_mutually_exclusive_group(required=True)
    context_pack_target.add_argument(
        "--job", dest="job_id", default=None, help="Agent job id to package"
    )
    context_pack_target.add_argument(
        "--task", dest="task_id", default=None, help="Task id to package"
    )
    p_context_pack.add_argument("--role", default=None, help="Reader role for this handoff")
    p_context_pack.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Approximate token budget for the generated Markdown package.",
    )
    p_context_pack.add_argument(
        "--record-usage",
        action="store_true",
        help="Explicitly record one local context_pack_generated usage event.",
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
    p_context_pack.add_argument(
        "--master-trace-context",
        action="store_true",
        help=(
            "Include task-linked master-trace and intent-index evidence references; "
            "valid only with --task."
        ),
    )
    p_context_check = context_sub.add_parser("check", help="Check target-bound context facts")
    context_check_target = p_context_check.add_mutually_exclusive_group(required=True)
    context_check_target.add_argument(
        "--job", dest="job_id", default=None, help="Agent job id to check"
    )
    context_check_target.add_argument(
        "--task", dest="task_id", default=None, help="Task id to check"
    )
    p_context_check.add_argument(
        "--require-bound-receipt",
        action="store_true",
        help="Exit with a typed error unless a matching target-bound code-context receipt is present.",
    )

    p_receipt = sub.add_parser("receipt", help="Inspect code context receipts")
    receipt_sub = p_receipt.add_subparsers(dest="receipt_command", required=True)
    p_receipt_show = receipt_sub.add_parser("show", help="Render a context receipt summary")
    p_receipt_show.add_argument(
        "ref", nargs="?", help="Context receipt evidence id or receipt path"
    )
    p_receipt_show.add_argument(
        "--latest",
        action="store_true",
        help="Show the most recent context_receipt evidence row.",
    )

    p_index = sub.add_parser("index", help="Build and inspect the code context index")
    index_sub = p_index.add_subparsers(dest="index_command", required=True)
    p_index_build = index_sub.add_parser(
        "build", help="Build a gitignore-aware code index snapshot"
    )
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
    rubric_source.add_argument(
        "--rubric-file", default=None, help="Read verification rubric JSON from a file"
    )
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
    p_decision_proposal = decision_sub.add_parser(
        "proposal",
        help="Inspect or human-select an immutable Profile Decision proposal",
    )
    decision_proposal_sub = p_decision_proposal.add_subparsers(
        dest="decision_proposal_command",
        required=True,
    )
    p_decision_proposal_show = decision_proposal_sub.add_parser("show")
    p_decision_proposal_show.add_argument("decision_id")
    p_decision_proposal_select = decision_proposal_sub.add_parser("select")
    p_decision_proposal_select.add_argument("decision_id")
    selection = p_decision_proposal_select.add_mutually_exclusive_group(required=True)
    selection.add_argument("--candidate", dest="candidate_id")
    selection.add_argument("--decline", action="store_true")
    p_decision_proposal_select.add_argument("--actor", required=True)
    p_decision_proposal_select.add_argument("--actor-kind", default=None)
    p_decision_proposal_select.add_argument("--recorded-by", default=None)
    p_decision_proposal_select.add_argument("--recorder-kind", default=None)
    p_decision_proposal_select.add_argument(
        "--source-kind",
        required=True,
        choices=["cli", "conversation", "cockpit", "api"],
    )
    p_decision_proposal_select.add_argument("--source-ref", required=True)
    p_decision_proposal_select.add_argument("--reason", required=True)
    p_decision_proposal_select.add_argument("--override-reason", default=None)

    p_escalation = sub.add_parser("escalation", help="Manage human escalations")
    escalation_sub = p_escalation.add_subparsers(dest="escalation_command", required=True)
    p_escalation_open = escalation_sub.add_parser("open")
    p_escalation_open.add_argument(
        "--severity", required=True, choices=["critical", "high", "medium", "low"]
    )
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
    p_escalation_list.add_argument(
        "--status", choices=["open", "resolved", "cancelled"], default=None
    )
    p_escalation_read = escalation_sub.add_parser("read")
    p_escalation_read.add_argument("escalation_id")

    p_checkpoint = sub.add_parser("checkpoint", help="Record and inspect integration checkpoints")
    checkpoint_sub = p_checkpoint.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_sub.add_parser("status", help="Inspect checkpoint recommendation state")
    p_checkpoint_record = checkpoint_sub.add_parser(
        "record", help="Record a human integration checkpoint"
    )
    p_checkpoint_record.add_argument("--summary", required=True)
    p_checkpoint_record.add_argument("--evidence", required=True)
    p_checkpoint_record.add_argument("--review-type", default="integration")

    p_guide = sub.add_parser(
        "guide", help="Show purpose-oriented command routes for agents and operators"
    )
    p_guide.add_argument(
        "topic",
        nargs="?",
        default=None,
        help="Optional topic: start, direct, finish, dashboard, or recover",
    )

    p_next = sub.add_parser("next", help="Suggest the next harness action")
    p_next.add_argument(
        "--strict",
        action="store_true",
        help="Route strict validation failures before normal next actions",
    )
    p_next.add_argument(
        "--explain",
        action="store_true",
        help="Print a human-readable explanation of the next action",
    )
    p_next.add_argument(
        "--target",
        dest="next_target",
        default=None,
        help="Bind routing to an existing Task or Goal ID",
    )

    p_finish = sub.add_parser("finish", help="Plan terminal loop close-out steps")
    p_finish.add_argument(
        "--execute",
        action="store_true",
        help="Run validate/render only when no finish steps remain",
    )
    p_finish.add_argument(
        "--emit-packet",
        action="store_true",
        help="Run configured guarded checks and emit a completion-packet/v1 artifact",
    )
    p_finish.add_argument(
        "--dry-run",
        action="store_true",
        help="With --emit-packet, preview the target, repository snapshot, and guarded check plan",
    )
    p_finish.add_argument("--run", default=None, help="Target a workflow run explicitly")
    p_finish.add_argument("--goal", default=None, help="Target a goal explicitly")
    p_finish.add_argument(
        "--task", default=None, help="Target a task for completion packet emission"
    )
    p_finish.add_argument(
        "--base", default=None, help="Git base revision for the completion packet diff"
    )
    p_finish.add_argument("--timeout", type=int, default=120, help="Per-check timeout in seconds")
    p_finish.add_argument(
        "--max-output-bytes",
        type=int,
        default=1_048_576,
        help="Maximum retained stdout and stderr bytes per check stream",
    )

    p_resume = sub.add_parser("resume", help="Build a read-only handoff packet for current work")
    p_resume.add_argument(
        "--target",
        dest="resume_target",
        default=None,
        help="Task or goal ID; required when multiple active targets exist",
    )
    p_resume.add_argument(
        "--format",
        choices=["json", "markdown"],
        default=None,
        help="Output format (default: markdown; --json selects JSON)",
    )
    p_resume.add_argument(
        "--output", default=None, help="Also write the rendered packet to this path"
    )

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
    p_report_kpi = report_sub.add_parser("kpi", help="Read local dogfood KPI measurements")
    p_report_kpi.add_argument(
        "--since", default=None, help="Include records on or after YYYY-MM-DD"
    )
    p_report_skill_usage = report_sub.add_parser(
        "skill-usage",
        help="Read local Codex, Claude, and Cockpit Skill usage without retaining raw logs",
    )
    p_report_skill_usage.add_argument(
        "--since",
        default=None,
        help="Include local log signals on or after YYYY-MM-DD (default: 30 days ago)",
    )
    p_report_skill_usage.add_argument(
        "--until",
        default=None,
        help="Include local log signals on or before YYYY-MM-DD (default: today)",
    )
    p_report_skill_usage.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source to scan: codex, claude, or cockpit. Repeat to select multiple.",
    )
    p_report_skill_usage.add_argument("--codex-root", default=None)
    p_report_skill_usage.add_argument("--claude-root", default=None)
    p_report_skill_usage.add_argument("--cockpit-root", default=None)
    p_report_skill_usage.add_argument(
        "--output",
        default=None,
        help="Also atomically write the privacy-safe JSON or Markdown report to this path",
    )

    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _print_legacy_evidence_warning(result: dict, *, json_output: bool) -> None:
    if json_output:
        return
    if any(
        warning.get("code") == "legacy_inline_evidence" for warning in result.get("warnings", [])
    ):
        print(
            "WARNING: --evidence is deprecated for terminal proof; use --evidence-id with hash-pinned Evidence.",
            file=sys.stderr,
        )


def _print_evidence_set_warnings(result: dict) -> None:
    for warning in result.get("warnings", []):
        print(
            "WARNING: Evidence set excluded "
            f"{warning['kind']} ({warning['status']}) at {warning['path']}; "
            f"required={str(warning['required']).lower()}.",
            file=sys.stderr,
        )


def _print_test_plan_warnings(result: dict) -> None:
    for warning in result.get("warnings", []):
        print(
            f"WARNING: {warning['message']} Suggested: {warning['suggested_command']}",
            file=sys.stderr,
        )


def _validate_contract_file(
    path_value: str,
    *,
    contract_type: str,
    json_output: bool,
) -> int:
    contract_handlers = {
        COMPLETION_PACKET_CONTRACT_VERSION: (
            load_completion_packet,
            validate_completion_packet,
        ),
        HANDOFF_PACKET_CONTRACT_VERSION: (load_handoff_packet, validate_handoff_packet),
        INTENT_INDEX_CONTRACT_VERSION: (load_intent_index, validate_intent_index),
        ROUTE_RECOMMENDATION_CONTRACT_VERSION: (
            load_route_recommendation,
            validate_route_recommendation,
        ),
        ROUTE_OVERRIDE_CONTRACT_VERSION: (load_route_override, validate_route_override),
        WORK_BRIEF_CONTRACT_VERSION: (load_work_brief, validate_work_brief),
        GAP_REPORT_CONTRACT_VERSION: (load_gap_report, validate_gap_report),
        EVIDENCE_SET_CONTRACT_VERSION: (load_evidence_set, validate_evidence_set),
        COMPLETION_POLICY_CONTRACT_VERSION: (
            load_completion_policy,
            validate_completion_policy,
        ),
        PROFILE_MANIFEST_CONTRACT_VERSION: (
            load_profile_manifest,
            validate_profile_manifest,
        ),
        PROFILE_RUN_REQUEST_CONTRACT_VERSION: (
            load_profile_run_request,
            validate_profile_run_request,
        ),
        PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION: (
            load_profile_output_bundle,
            validate_profile_output_bundle,
        ),
        COUNCIL_RUN_CONTRACT_VERSION: (load_council_run, validate_council_run),
        CLAIM_SET_CONTRACT_VERSION: (load_claim_set, validate_claim_set),
        VERIFICATION_PLAN_CONTRACT_VERSION: (
            load_verification_plan,
            validate_verification_plan,
        ),
        DECISION_PROPOSAL_CONTRACT_VERSION: (
            load_decision_proposal,
            validate_decision_proposal,
        ),
    }
    load_packet, validate_packet = contract_handlers[contract_type]
    try:
        packet = load_packet(path_value)
    except OSError as exc:
        raise InvalidInputError(
            f"Could not read contract file: {path_value}",
            details={"path": path_value, "reason": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise InvalidInputError(
            f"Contract file is not valid JSON: {path_value}",
            details={"column": exc.colno, "line": exc.lineno, "path": path_value},
        ) from exc
    except ValueError as exc:
        raise InvalidInputError(
            f"Contract file contains an invalid JSON value: {path_value}",
            details={"path": path_value, "reason": str(exc)},
        ) from exc

    result = validate_packet(packet)
    payload = result.to_dict()
    payload["path"] = path_value
    if json_output:
        _print_json(payload)
    elif result.ok:
        print(f"Valid {contract_type}: {path_value}")
    else:
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if result.ok else 1


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
        if args.command == "guide":
            return handle_guide(args.topic, json_output=json_output, output=sys.stdout)

        if args.command == "profile" and args.profile_command == "list":
            result = list_profiles()
            if json_output:
                _print_json(result)
            else:
                for profile in result["profiles"]:
                    routes = ",".join(profile["supported_routes"])
                    print(
                        f"{profile['runner_profile_id']} {profile['profile_version']} "
                        f"{profile['display_name']} routes={routes} "
                        f"source={profile['source']} executed_by_plh=false"
                    )
            return 0

        if args.command == "profile" and args.profile_command == "show":
            result = show_profile(args.runner_profile_id)
            if json_output:
                _print_json(result)
            else:
                manifest = result["manifest"]
                print(
                    f"Runner Profile: {result['runner_profile_id']} "
                    f"version={manifest['profile_version']}"
                )
                print(
                    f"Source: {result['source']} trust={result['trust']} "
                    f"executed_by_plh=false"
                )
                print(f"Manifest SHA-256: {result['manifest_sha256']}")
                print(f"Routes: {', '.join(manifest['supported_routes'])}")
                print(
                    "Terminology: route_profile selects Direct/Discover/Assure; "
                    "role_profile selects context packing."
                )
            return 0

        if args.command == "profile" and args.profile_command == "validate":
            result = validate_profile(args.runner_profile_id)
            if json_output:
                _print_json(result)
            elif result["ok"]:
                print(
                    f"Valid built-in runner Profile: {result['runner_profile_id']} "
                    f"sha256={result['manifest_sha256']}"
                )
            else:
                for error in result["errors"]:
                    print(f"ERROR: {error}", file=sys.stderr)
            return 0 if result["ok"] else 1

        if args.command == "profile" and args.profile_command == "prepare":
            result = prepare_profile_request(
                paths,
                runner_profile_id=args.runner_profile_id,
                target_ref=args.target_ref,
                brief_id=args.brief_id,
                output=args.output,
                network_access=args.network_access,
                paid_service_requested=args.paid_service,
                allowed_providers=args.provider,
                repository_content_policy=args.repository_content_policy,
                monetary_budget=args.monetary_budget,
                currency=args.currency,
            )
            if json_output:
                _print_json(result)
            elif result["output_path"]:
                print(
                    f"Prepared {args.runner_profile_id} request at "
                    f"{result['output_path']} (runner_executed=false)"
                )
            else:
                print(to_pretty_json(result["request"]))
            return 0

        if args.command == "profile" and args.profile_command == "ingest":
            operation = plan_profile_ingest if args.dry_run else ingest_profile_bundle
            result = operation(
                paths,
                request_file=args.request_file,
                bundle_file=args.bundle_file,
                accept_failed=args.accept_failed,
                summary=args.summary,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "profile" and args.profile_command == "authorize":
            provenance = {
                "actor": args.actor,
                "actor_kind": args.actor_kind,
                "recorded_by": args.recorded_by,
                "recorder_kind": args.recorder_kind,
                "source_kind": args.source_kind,
                "source_ref": args.source_ref,
                "reason": args.reason,
            }
            if args.authorized_event_id:
                if args.request_file or args.output:
                    raise ProfileAuthorizationError(
                        message="--revoke cannot be combined with --request or --output.",
                        code="profile_authorization_revoke_arguments",
                        exit_code=2,
                        details={},
                    )
                result = revoke_profile_authorization(
                    paths,
                    authorized_event_id=args.authorized_event_id,
                    **provenance,
                )
            else:
                if not args.request_file or not args.output:
                    raise ProfileAuthorizationError(
                        message="--request and --output are required unless --revoke is used.",
                        code="profile_authorization_request_arguments",
                        exit_code=2,
                        details={},
                    )
                result = authorize_profile_request(
                    paths,
                    request_file=args.request_file,
                    output=args.output,
                    max_cost=args.max_cost,
                    currency=args.currency,
                    allowed_providers=args.provider,
                    data_classes=args.data_class,
                    expires_at=args.expires_at,
                    **provenance,
                )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "profile" and args.profile_command == "fixture-run":
            result = run_profile_fixture(
                request_file=args.request_file,
                status=args.status,
                output_dir=args.output_dir,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "contract" and args.contract_command == "validate":
            return _validate_contract_file(
                args.file,
                contract_type=args.contract_type,
                json_output=json_output,
            )

        if args.command == "evidence-set" and args.evidence_set_command == "plan":
            result = plan_evidence_set(
                paths,
                target_ref=args.target_ref,
                work_root=args.work_root,
                manifest_file=args.manifest_file,
                required_kinds=args.required_kinds,
                included_refs=args.included_refs,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result["plan"]))
                _print_evidence_set_warnings(result)
            return 0

        if args.command == "evidence-set" and args.evidence_set_command == "record":
            result = record_evidence_set(
                paths,
                target_ref=args.target_ref,
                work_root=args.work_root,
                manifest_file=args.manifest_file,
                required_kinds=args.required_kinds,
                included_refs=args.included_refs,
                summary=args.summary,
            )
            if json_output:
                _print_json(result)
            else:
                evidence = result["evidence"]
                print(f"{evidence['id']} completeness={evidence['completeness_status']}")
                _print_evidence_set_warnings(result)
            return 0

        if args.command == "evidence-set" and args.evidence_set_command == "show":
            result = show_evidence_set(paths, evidence_id=args.evidence_id)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result["evidence_set"]))
            return 0

        if args.command == "completion" and args.completion_command == "evaluate":
            result = evaluate_completion_policy(
                paths,
                policy_file=args.policy_file,
                evidence_set_id=args.evidence_set_id,
                test_case_id=args.test_case_id,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result["evaluation"]))
            return 0 if result["ok"] else 1

        if args.command == "brief" and args.brief_command == "add":
            result = add_work_brief(
                paths,
                file=args.file,
                summary=args.summary,
                dry_run=args.dry_run,
            )
            if json_output:
                _print_json(result)
            elif args.dry_run:
                print(to_pretty_json(result["planned"]))
            else:
                evidence = result["evidence"]
                print(f"{evidence['id']} {evidence['brief_id']} revision={evidence['revision']}")
            return 0

        if args.command == "brief" and args.brief_command == "show":
            result = show_work_brief(
                paths,
                evidence_id=args.evidence_id,
                target_ref=args.target_ref,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "brief" and args.brief_command == "approve":
            result = approve_work_brief(
                paths,
                evidence_id=args.evidence_id,
                actor=args.actor,
                actor_kind=args.actor_kind,
                recorded_by=args.recorded_by,
                recorder_kind=args.recorder_kind,
                source_kind=args.source_kind,
                source_ref=args.source_ref,
                reason=args.reason,
                dry_run=args.dry_run,
            )
            if json_output:
                _print_json(result)
            elif args.dry_run:
                print(to_pretty_json(result["planned"]))
            elif result["changed"]:
                print(f"Approved Work Brief Evidence {args.evidence_id}")
            else:
                print(f"Work Brief Evidence {args.evidence_id} is already approved")
            return 0

        if args.command == "brief" and args.brief_command == "review":
            result = review_work_brief(
                paths,
                evidence_id=args.evidence_id,
                actor=args.actor,
                actor_kind=args.actor_kind,
                reason=args.reason,
                dry_run=args.dry_run,
            )
            if json_output:
                _print_json(result)
            elif args.dry_run:
                print(to_pretty_json(result["planned"]))
            else:
                print(f"Recorded Work Brief review {result['event_id']}")
            return 0

        if args.command == "gap" and args.gap_command == "add":
            result = add_gap_report(
                paths,
                file=args.file,
                summary=args.summary,
                dry_run=args.dry_run,
            )
            if json_output:
                _print_json(result)
            elif args.dry_run:
                print(to_pretty_json(result["planned"]))
            else:
                evidence = result["evidence"]
                print(f"{evidence['id']} gap_class={evidence['gap_class']}")
            return 0

        if args.command == "gap" and args.gap_command == "show":
            result = show_gap_report(paths, evidence_id=args.evidence_id)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "gap" and args.gap_command == "list":
            result = list_gap_reports(
                paths,
                target_ref=args.target_ref,
                gap_class=args.gap_class,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "gap" and args.gap_command == "promote":
            result = promote_gap_lesson(
                paths,
                evidence_id=args.evidence_id,
                lesson_id=args.lesson_id,
                actor=args.actor,
                actor_kind=args.actor_kind,
                recorded_by=args.recorded_by,
                recorder_kind=args.recorder_kind,
                source_kind=args.source_kind,
                source_ref=args.source_ref,
                reason=args.reason,
                dry_run=args.dry_run,
            )
            if json_output:
                _print_json(result)
            elif args.dry_run:
                print(to_pretty_json(result["planned"]))
            elif result["changed"]:
                print(
                    f"Approved candidate lesson {args.lesson_id}; durable-owner application pending"
                )
            else:
                print(f"Candidate lesson {args.lesson_id} promotion is already approved")
            return 0

        if args.command == "route" and args.route_command == "recommend":
            result = recommend_route(
                paths,
                target_ref=args.target_ref,
                brief_file=args.brief_file,
                changed_paths=args.changed_paths,
                record=args.record,
            )
            if json_output:
                _print_json(result)
            elif args.record and result["changed"]:
                print(
                    f"{result['evidence']['id']} "
                    f"{result['recommendation']['profile']} "
                    f"risk={result['recommendation']['risk_level']}"
                )
            else:
                print(to_pretty_json(result["recommendation"]))
            return 0

        if args.command == "route" and args.route_command == "override":
            result = override_route(
                paths,
                target_ref=args.target_ref,
                requested_profile=args.requested_profile,
                actor=args.actor,
                reason=args.reason,
                brief_file=args.brief_file,
                changed_paths=args.changed_paths,
                policy_file=args.policy_file,
                dry_run=args.dry_run,
            )
            if json_output:
                _print_json(result)
            elif args.dry_run:
                print(to_pretty_json(result["planned"]))
            elif result["changed"]:
                print(
                    f"{result['evidence']['override']['id']} "
                    f"profile={result['override']['requested_profile']}"
                )
            else:
                print(f"Route override already recorded: {result['evidence']['override']['id']}")
            return 0

        if args.command == "route" and args.route_command == "current":
            result = current_route(
                paths,
                target_ref=args.target_ref,
                brief_file=args.brief_file,
                changed_paths=args.changed_paths,
                policy_file=args.policy_file,
            )
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return 0

        if args.command == "policy" and args.policy_command in {"resolve", "explain"}:
            result = resolve_policy_for_target(
                paths,
                target_ref=args.target_ref,
                brief_file=args.brief_file,
                changed_paths=args.changed_paths,
                policy_file=args.policy_file,
            )
            if json_output:
                _print_json(result)
            elif args.policy_command == "explain":
                print(render_policy_explanation(result["resolution"]), end="")
            else:
                print(to_pretty_json(result["resolution"]))
            return 0

        if args.command == "resume":
            if json_output and args.format == "markdown":
                raise InvalidInputError("--json cannot be combined with --format markdown.")
            output_format = "json" if json_output else (args.format or "markdown")
            output_path = Path(args.output) if args.output else None
            if output_path is not None:
                resolved_output = output_path.resolve()
                loop_dir = paths.loop_dir.resolve()
                exports_dir = paths.exports_dir.resolve()
                if resolved_output.is_relative_to(loop_dir) and not resolved_output.is_relative_to(
                    exports_dir
                ):
                    raise InvalidInputError(
                        "--output cannot overwrite Project Loop state; use .project-loop/exports or a path outside .project-loop.",
                        details={
                            "path": args.output,
                            "allowed_project_loop_dir": str(paths.exports_dir),
                        },
                    )
            packet = build_handoff_packet(paths, target_id=args.resume_target)
            rendered = (
                serialized_handoff_packet(packet)
                if output_format == "json"
                else render_handoff_markdown(packet)
            )
            if output_path is not None:
                try:
                    output_path.write_text(rendered, encoding="utf-8")
                except OSError as exc:
                    raise InvalidInputError(
                        f"Could not write handoff packet: {args.output}",
                        details={"path": args.output, "reason": str(exc)},
                    ) from exc
            if output_format == "json":
                payload: dict[str, object] = {"ok": True, "handoff_packet": packet}
                if args.output:
                    payload["output"] = args.output
                _print_json(payload)
            elif args.output:
                print(args.output)
            else:
                print(rendered, end="")
            return 0

        if args.command == "init":
            if args.dry_run:
                plan = plan_init_project(
                    paths,
                    overwrite=args.force,
                    with_claude=not args.no_claude,
                    repair_config=args.repair_config,
                    refresh_skill=args.refresh_skill,
                )
                return _print_init_plan(plan, json_output=json_output)
            result = init_project(
                paths,
                overwrite=args.force,
                with_claude=not args.no_claude,
                repair_config=args.repair_config,
                refresh_skill=args.refresh_skill,
            )
            if json_output:
                payload = {
                    "ok": True,
                    "root": str(result.root),
                    "created": result.created,
                    "event_appended": result.event_appended,
                }
                if args.repair_config:
                    payload["repaired_config_commands"] = list(
                        result.repaired_config_commands
                    )
                if args.refresh_skill:
                    payload["skill_refreshed"] = result.skill_refreshed
                    payload["skill_backup_path"] = result.skill_backup_path
                _print_json(payload)
            else:
                print(f"Initialized Project Loop Harness at {paths.root}")
                if result.repaired_config_commands:
                    print(
                        "Repaired legacy empty commands: "
                        + ", ".join(result.repaired_config_commands)
                    )
            return 0

        if args.command == "start":
            payload = start_work(
                paths,
                intent=args.intent,
                dry_run=args.dry_run,
                no_init=args.no_init,
                new=args.new,
                skills=args.skill,
            )
            if json_output:
                _print_json(payload)
            else:
                print(_format_start_summary(payload))
            return 1 if payload["status"] == "init_blocked" else 0

        if args.command == "doctor":
            return handle_doctor(
                paths,
                strict=args.strict,
                check_updates=args.check_updates,
                json_output=json_output,
                output=sys.stdout,
            )

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

        if args.command == "audit" and args.audit_command == "flush":
            result = project_pending_events(paths)
            if json_output:
                _print_json({"ok": result.ok, **result.to_dict()})
            else:
                print(to_pretty_json(result.to_dict()))
            return 0 if result.ok else 6

        if args.command == "audit" and args.audit_command == "check":
            result = audit_check(paths)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return audit_check_exit_code(result)

        if args.command == "audit" and args.audit_command == "repair":
            result = audit_repair(paths, apply=args.apply)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return audit_repair_exit_code(result)

        if args.command == "audit" and args.audit_command == "rebuild-jsonl":
            output = None if args.output is None else Path(args.output).resolve()
            try:
                result = rebuild_jsonl_from_sqlite(paths, output=output, apply=args.apply)
            except OSError as exc:
                raise AuditCommandError(
                    message=f"Audit JSONL rebuild was interrupted by an I/O error: {exc}",
                    code="audit_rebuild_io_error",
                    exit_code=6,
                ) from exc
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result))
            return audit_rebuild_exit_code(result)

        if args.command == "repair" and args.repair_command == "lifecycle":
            if args.apply:
                raise InvalidInputError(
                    "--apply is not supported; use --apply-structural.",
                    details={"flag": "--apply", "supported_flag": "--apply-structural"},
                )
            if args.apply_structural:
                result = apply_structural_lifecycle_repair(paths)
                if json_output:
                    _print_json(result)
                else:
                    print(to_pretty_json(result))
                return 0
            plan = build_lifecycle_repair_plan(paths)
            if json_output:
                _print_json(plan)
            else:
                print(render_lifecycle_repair_plan(plan))
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

        entity_status = handle_entity_command(
            args,
            paths,
            json_output=json_output,
            output=sys.stdout,
            error=sys.stderr,
        )
        if entity_status is not None:
            return entity_status

        if args.command == "loop" and args.loop_command == "status":
            return handle_loop_status(paths, json_output=json_output, output=sys.stdout)

        execution_status = handle_execution_command(
            args,
            paths,
            json_output=json_output,
            output=sys.stdout,
            error=sys.stderr,
        )
        if execution_status is not None:
            return execution_status

        governance_status = handle_governance_command(
            args,
            paths,
            json_output=json_output,
            rubric_json=_rubric_json_argument(args)
            if args.command == "verification" and args.verification_command == "record"
            else None,
            output=sys.stdout,
            error=sys.stderr,
        )
        if governance_status is not None:
            return governance_status

        if args.command == "context" and args.context_command == "pack":
            now = utc_now_iso()
            if args.job_id:
                if args.master_trace_context:
                    raise InvalidInputError(
                        "--master-trace-context is valid only with --task.",
                        details={"master_trace_context": True, "target_type": "agent_job"},
                    )
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
                    include_master_trace_context=args.master_trace_context,
                )
            if args.record_usage:
                record_context_pack_usage(paths, pack)
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
                print(_format_context_check_summary(payload))
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
                            "findings": [finding.to_dict() for finding in validation.findings],
                            "finding_count": len(validation.findings),
                            "finding_counts": validation.finding_counts(),
                            "finding_codes": [finding.code for finding in validation.findings],
                            "validation_report": ".project-loop/reports/validation-strict.md",
                        },
                        priority=1,
                        blocking=True,
                        requires_human=True,
                        safe_to_run=True,
                        expected_after="Strict validation passes and normal next-action routing can resume.",
                    )
                else:
                    action = next_action(paths, target=args.next_target)
            else:
                action = next_action(paths, target=args.next_target)
            if json_output:
                _print_json(action)
            elif args.explain:
                print(_format_next_explanation(action))
            else:
                print(to_pretty_json(action))
            return 0

        if args.command == "finish":
            packet_only_flags = any(
                [
                    args.dry_run,
                    args.task,
                    args.base,
                    args.timeout != 120,
                    args.max_output_bytes != 1_048_576,
                ]
            )
            if args.execute and args.emit_packet:
                raise InvalidInputError(
                    "--execute and --emit-packet are separate modes and cannot be combined."
                )
            if packet_only_flags and not args.emit_packet:
                raise InvalidInputError(
                    "--dry-run, --task, --base, --timeout, and --max-output-bytes require --emit-packet."
                )
            if args.emit_packet:
                if args.dry_run:
                    packet_payload = plan_finish_packet(
                        paths,
                        run_id=args.run,
                        goal_id=args.goal,
                        task_id=args.task,
                        base_revision=args.base,
                    )
                    packet_payload["exit_code"] = 0
                else:
                    packet_payload = emit_finish_packet(
                        paths,
                        run_id=args.run,
                        goal_id=args.goal,
                        task_id=args.task,
                        base_revision=args.base,
                        timeout_seconds=args.timeout,
                        max_output_bytes=args.max_output_bytes,
                    )
                if json_output:
                    _print_json({"ok": True, "finish": packet_payload})
                else:
                    print(to_pretty_json(packet_payload))
                return int(packet_payload["exit_code"])
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

        if args.command == "report" and args.report_command in {
            "goal",
            "run",
            "feature",
            "defect",
            "validation",
        }:
            identifier_attributes = {
                "goal": "goal_id",
                "run": "workflow_run_id",
                "feature": "feature_id",
                "defect": "defect_id",
            }
            identifier = getattr(
                args,
                identifier_attributes.get(args.report_command, ""),
                None,
            )
            return handle_report_artifact(
                paths,
                args.report_command,
                identifier=identifier,
                strict=getattr(args, "strict", False),
                json_output=json_output,
                output=sys.stdout,
            )

        if args.command == "report" and args.report_command == "kpi":
            result = report_kpi(paths, since=args.since)
            if json_output:
                _print_json(result)
            else:
                print(to_pretty_json(result["sections"]))
            return 0

        if args.command == "report" and args.report_command == "skill-usage":
            result = report_skill_usage(
                since=args.since,
                until=args.until,
                sources=args.source or None,
                codex_root=args.codex_root,
                claude_root=args.claude_root,
                cockpit_root=args.cockpit_root,
            )
            rendered = (
                serialized_skill_usage_report(result)
                if json_output
                else render_skill_usage_markdown(result)
            )
            if args.output:
                source_roots = default_skill_usage_roots(
                    codex_root=args.codex_root,
                    claude_root=args.claude_root,
                    cockpit_root=args.cockpit_root,
                )
                write_skill_usage_report(
                    args.output,
                    rendered,
                    forbidden_roots=source_roots.values(),
                    forbidden_paths=(
                        paths.db_path,
                        paths.events_path,
                        paths.dashboard_html,
                        paths.dashboard_data,
                    ),
                )
            print(rendered, end="")
            return 0

        parser.error("Unhandled command")
        return 2
    except PclError as exc:
        _print_error(exc, json_output=json_output)
        return exc.exit_code
    except OSError as exc:
        if args.command == "audit":
            error = AuditCommandError(
                message=f"Audit command failed: {exc}",
                code="audit_internal_error",
                exit_code=EXIT_AUDIT_INTERNAL,
            )
            _print_error(error, json_output=json_output)
            return error.exit_code
        raise
    except sqlite3.Error as exc:
        if args.command == "audit":
            error = AuditCommandError(
                message=f"SQLite error while running audit: {exc}",
                code="audit_internal_error",
                exit_code=EXIT_AUDIT_INTERNAL,
            )
            _print_error(error, json_output=json_output)
            return error.exit_code
        error = DataStoreError(f"SQLite error while running {args.command}: {exc}")
        _print_error(error, json_output=json_output)
        return error.exit_code
    except Exception as exc:
        if args.command == "audit":
            error = AuditCommandError(
                message=f"Audit command failed unexpectedly: {exc}",
                code="audit_internal_error",
                exit_code=EXIT_AUDIT_INTERNAL,
            )
            _print_error(error, json_output=json_output)
            return error.exit_code
        raise


if __name__ == "__main__":
    raise SystemExit(main())
