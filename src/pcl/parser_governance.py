from __future__ import annotations

from .parser_common import choices_help
from .verifications import VERIFICATION_RESULTS


def add_governance_parsers(sub) -> None:
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
        help=f"Filter by verification result: {choices_help(VERIFICATION_RESULTS)}",
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
