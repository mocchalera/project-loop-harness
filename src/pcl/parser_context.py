from __future__ import annotations

from .code_index import GIT_DIFF_SENTINEL
from .context import DEFAULT_MAX_TOKENS


def add_context_parsers(sub) -> None:
    p_progress = sub.add_parser(
        "progress",
        help="Record progress receipts and manage the optional Progress Guard",
    )
    progress_sub = p_progress.add_subparsers(
        dest="progress_command",
        required=True,
    )
    p_progress_record = progress_sub.add_parser(
        "record",
        help="Record one immutable progress receipt without changing target status",
    )
    progress_target = p_progress_record.add_mutually_exclusive_group(required=True)
    progress_target.add_argument(
        "--task",
        dest="task_id",
        help="Exact task target for this progress receipt",
    )
    progress_target.add_argument(
        "--goal",
        dest="goal_id",
        help="Exact goal target for this progress receipt",
    )
    p_progress_record.add_argument("--milestone", required=True)
    p_progress_record.add_argument("--status", required=True)
    p_progress_record.add_argument("--blocker", action="append", default=[])
    p_progress_record.add_argument("--evidence-id", default=None)
    p_progress_record.add_argument(
        "--execution-root",
        default=None,
        help="Execution worktree root; defaults to the canonical PCL root",
    )
    p_progress_record.add_argument("--cockpit-task-id", default=None)
    p_progress_record.add_argument(
        "--cockpit-report-seq",
        dest="cockpit_report_sequence",
        type=int,
        default=None,
    )
    p_progress_record.add_argument("--cockpit-report-ref", default=None)
    p_progress_record.add_argument("--ci-provider", default=None)
    p_progress_record.add_argument("--ci-run-id", default=None)
    p_progress_record.add_argument("--ci-run-url", default=None)

    p_progress_guard = progress_sub.add_parser(
        "guard",
        help="Manage the opt-in cooperative Mainline Progress Guard",
        description=(
            "Practical policy enforcement for normal PCL agents. This is not "
            "tamper-proof security or cryptographic human authentication."
        ),
    )
    guard_sub = p_progress_guard.add_subparsers(
        dest="progress_guard_command",
        required=True,
    )

    def add_lineage(parser) -> None:
        parser.add_argument("--goal", dest="goal_id", required=True)
        parser.add_argument("--exit-gate", required=True)

    p_guard_activate = guard_sub.add_parser(
        "activate",
        help="Opt one existing Goal/Exit-Gate lineage into the policy",
    )
    add_lineage(p_guard_activate)
    p_guard_activate.add_argument("--limit", type=int, default=2)

    p_guard_status = guard_sub.add_parser(
        "status",
        help="Derive deterministic current guard state from Events",
    )
    add_lineage(p_guard_status)

    p_guard_observe = guard_sub.add_parser(
        "observe",
        help="Record one bound mainline/support/deferred observation",
    )
    add_lineage(p_guard_observe)
    p_guard_observe.add_argument("--delta", type=int, choices=[0, 1], required=True)
    p_guard_observe.add_argument(
        "--classification",
        choices=["mainline_product", "harness_support", "deferred"],
        required=True,
    )
    p_guard_observe.add_argument(
        "--value-kind",
        choices=[
            "criterion_closed",
            "gate_bound_artifact_ready",
            "human_acceptance",
            "integrated_behavior",
        ],
    )
    p_guard_observe.add_argument("--criterion", required=True)
    p_guard_observe.add_argument("--surface", required=True)
    p_guard_observe.add_argument("--value-token", required=True)
    p_guard_observe.add_argument("--summary", required=True)
    p_guard_observe.add_argument("--evidence-ref", required=True)
    p_guard_observe.add_argument("--task-label")
    p_guard_observe.add_argument("--run-label")
    p_guard_observe.add_argument("--route-label")

    p_guard_replan = guard_sub.add_parser(
        "replan",
        help=(
            "Record an operator attestation and resume; this is visible audit "
            "state, not cryptographic human authentication"
        ),
    )
    add_lineage(p_guard_replan)
    p_guard_replan.add_argument("--revision-token", required=True)
    p_guard_replan.add_argument("--reason", required=True)
    p_guard_replan.add_argument("--operator", required=True)

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
