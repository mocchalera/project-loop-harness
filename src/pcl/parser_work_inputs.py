from __future__ import annotations

from .contracts.claim_set import CLAIM_SET_CONTRACT_VERSION
from .contracts.completion_packet import COMPLETION_PACKET_CONTRACT_VERSION
from .contracts.completion_policy import COMPLETION_POLICY_CONTRACT_VERSION
from .contracts.council_run import COUNCIL_RUN_CONTRACT_VERSION
from .contracts.decision_proposal import DECISION_PROPOSAL_CONTRACT_VERSION
from .contracts.evidence_set import EVIDENCE_SET_CONTRACT_VERSION
from .contracts.gap_report import GAP_CLASSES, GAP_REPORT_CONTRACT_VERSION
from .contracts.handoff_packet import HANDOFF_PACKET_CONTRACT_VERSION
from .contracts.intent_index import INTENT_INDEX_CONTRACT_VERSION
from .contracts.profile_manifest import PROFILE_MANIFEST_CONTRACT_VERSION
from .contracts.profile_output_bundle import PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION
from .contracts.profile_run_request import PROFILE_RUN_REQUEST_CONTRACT_VERSION
from .contracts.route_override import ROUTE_OVERRIDE_CONTRACT_VERSION
from .contracts.route_recommendation import ROUTE_RECOMMENDATION_CONTRACT_VERSION
from .contracts.verification_plan import VERIFICATION_PLAN_CONTRACT_VERSION
from .contracts.work_brief import WORK_BRIEF_CONTRACT_VERSION


def add_work_input_parsers(sub) -> None:
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
