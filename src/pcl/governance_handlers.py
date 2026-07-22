from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from .checkpoints import checkpoint_status, record_checkpoint
from .decisions import (
    list_decisions,
    open_decision,
    read_decision,
    resolve_decision,
    waive_decision,
)
from .errors import InvalidInputError
from .escalations import (
    cancel_escalation,
    list_escalations,
    open_escalation,
    read_escalation,
    resolve_escalation,
)
from .evidence import record_adhoc_evidence, supersede_evidence
from .evidence_show import render_evidence_metadata, show_evidence
from .lifecycle import record_verification
from .paths import ProjectPaths
from .presentation import to_pretty_json
from .profile_decisions import select_profile_proposal, show_profile_proposal
from .relationship_repair import add_evidence_link
from .verification_feedback import record_verification_feedback, verification_feedback_stats
from .verifications import list_verifications, read_verification


GOVERNANCE_COMMANDS = frozenset(
    {"evidence", "verification", "decision", "escalation", "checkpoint"}
)


def handle_governance_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    rubric_json: str | None = None,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int | None:
    """Handle Evidence and human-governance commands, or return ``None``."""

    if args.command not in GOVERNANCE_COMMANDS:
        return None

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
            _write_json(result, output)
        else:
            for warning in result.get("warnings", []):
                print(f"WARNING: {warning}", file=error)
            evidence = result["evidence"]
            print(f"{evidence['id']} {evidence['type']} {evidence['manifest_path']}", file=output)
        return 0

    if args.command == "evidence" and args.evidence_command == "show":
        result = show_evidence(paths, args.evidence_id)
        _write_json(result, output) if json_output else print(
            render_evidence_metadata(result), end="", file=output
        )
        return 0

    if args.command == "evidence" and args.evidence_command == "supersede":
        result = supersede_evidence(
            paths,
            evidence_id=args.evidence_id,
            replacement_evidence_id=args.replacement_evidence_id,
            summary=args.summary,
        )
        if json_output:
            _write_json(result, output)
        else:
            print(
                f"Evidence {result['evidence_id']} superseded by {result['superseded_by']}"
                + ("" if result["changed"] else " (already recorded)"),
                file=output,
            )
        return 0

    if args.command == "evidence" and args.evidence_command == "link":
        target_type, separator, target_id = args.target_ref.partition(":")
        if not separator or not target_type or not target_id:
            raise InvalidInputError(
                "--target must be formatted as <target-type>:<target-id>.",
                details={"target": args.target_ref},
            )
        result = add_evidence_link(
            paths,
            evidence_id=args.evidence_id,
            target_type=target_type,
            target_id=target_id,
            role=args.role,
            summary=args.summary,
        )
        _write_json(result, output) if json_output else print(
            to_pretty_json(result), file=output
        )
        return 0

    if args.command == "verification" and args.verification_command == "record":
        result = record_verification(
            paths,
            workflow_run_id=args.run,
            result=args.result,
            reasons=args.reason,
            verifier_role=args.verifier_role,
            rubric_json=rubric_json or "{}",
            target_job_id=args.target_job,
        )
        _write_json(result, output) if json_output else print(result["id"], file=output)
        return 0

    if args.command == "verification" and args.verification_command == "list":
        verifications = list_verifications(
            paths,
            workflow_run_id=args.run,
            result=args.result,
        )
        if json_output:
            _write_json({"ok": True, "verifications": verifications}, output)
        elif verifications:
            for verification in verifications:
                print(
                    f"{verification['id']} {verification['result']} "
                    f"run={verification['workflow_run_id']} "
                    f"target_job={verification['target_job_id'] or ''}",
                    file=output,
                )
        else:
            print("No verifications", file=output)
        return 0

    if args.command == "verification" and args.verification_command == "read":
        verification = read_verification(paths, args.verification_id)
        if json_output:
            _write_json({"ok": True, "verification": verification}, output)
        else:
            print(to_pretty_json(verification), file=output)
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
        _write_json(result, output) if json_output else print(
            result["feedback"]["id"], file=output
        )
        return 0

    if args.command == "verification" and args.verification_command == "stats":
        result = verification_feedback_stats(paths)
        _write_json(result, output) if json_output else print(
            to_pretty_json(result["stats"]), file=output
        )
        return 0

    if args.command == "decision" and args.decision_command == "open":
        result = open_decision(
            paths,
            question=args.question,
            recommendation=args.recommendation,
            blocks_json=args.blocks_json,
            escalation_id=args.escalation,
        )
        _write_json(result, output) if json_output else print(result["id"], file=output)
        return 0

    if args.command == "decision" and args.decision_command == "resolve":
        result = resolve_decision(
            paths,
            decision_id=args.decision_id,
            selected_option=args.selected_option,
            reason=args.reason,
        )
        _write_json(result, output) if json_output else print(
            f"Resolved decision {result['id']}", file=output
        )
        return 0

    if args.command == "decision" and args.decision_command == "waive":
        result = waive_decision(paths, decision_id=args.decision_id, reason=args.reason)
        _write_json(result, output) if json_output else print(
            f"Waived decision {result['id']}", file=output
        )
        return 0

    if args.command == "decision" and args.decision_command == "list":
        decisions = list_decisions(paths, status=args.status)
        if json_output:
            _write_json({"ok": True, "decisions": decisions}, output)
        elif decisions:
            for decision in decisions:
                print(
                    f"{decision['id']} {decision['status']} question={decision['question']}",
                    file=output,
                )
        else:
            print("No decisions", file=output)
        return 0

    if args.command == "decision" and args.decision_command == "read":
        decision = read_decision(paths, args.decision_id)
        _write_json({"ok": True, "decision": decision}, output) if json_output else print(
            to_pretty_json(decision), file=output
        )
        return 0

    if args.command == "decision" and args.decision_command == "proposal":
        if args.decision_proposal_command == "show":
            result = show_profile_proposal(paths, args.decision_id)
        else:
            result = select_profile_proposal(
                paths,
                decision_id=args.decision_id,
                candidate_id=args.candidate_id,
                decline=args.decline,
                actor=args.actor,
                actor_kind=args.actor_kind,
                recorded_by=args.recorded_by,
                recorder_kind=args.recorder_kind,
                source_kind=args.source_kind,
                source_ref=args.source_ref,
                reason=args.reason,
                override_reason=args.override_reason,
            )
        _write_json(result, output) if json_output else print(
            to_pretty_json(result), file=output
        )
        return 0

    if args.command == "escalation" and args.escalation_command == "open":
        result = open_escalation(
            paths,
            severity=args.severity,
            question=args.question,
            recommendation=args.recommendation,
            workflow_run_id=args.run,
        )
        _write_json(result, output) if json_output else print(result["id"], file=output)
        return 0

    if args.command == "escalation" and args.escalation_command == "resolve":
        result = resolve_escalation(
            paths,
            escalation_id=args.escalation_id,
            summary=args.summary,
            decision_id=args.decision,
        )
        _write_json(result, output) if json_output else print(
            f"Resolved escalation {result['id']}", file=output
        )
        return 0

    if args.command == "escalation" and args.escalation_command == "cancel":
        result = cancel_escalation(
            paths,
            escalation_id=args.escalation_id,
            summary=args.summary,
        )
        _write_json(result, output) if json_output else print(
            f"Cancelled escalation {result['id']}", file=output
        )
        return 0

    if args.command == "escalation" and args.escalation_command == "list":
        escalations = list_escalations(paths, status=args.status)
        if json_output:
            _write_json({"ok": True, "escalations": escalations}, output)
        elif escalations:
            for escalation in escalations:
                print(
                    f"{escalation['id']} {escalation['status']} "
                    f"severity={escalation['severity']} "
                    f"run={escalation['workflow_run_id'] or ''}",
                    file=output,
                )
        else:
            print("No escalations", file=output)
        return 0

    if args.command == "escalation" and args.escalation_command == "read":
        escalation = read_escalation(paths, args.escalation_id)
        if json_output:
            _write_json({"ok": True, "escalation": escalation}, output)
        else:
            print(to_pretty_json(escalation), file=output)
        return 0

    if args.command == "checkpoint" and args.checkpoint_command == "status":
        status = checkpoint_status(paths)
        _write_json(status, output) if json_output else print(to_pretty_json(status), file=output)
        return 0

    if args.command == "checkpoint" and args.checkpoint_command == "record":
        result = record_checkpoint(
            paths,
            summary=args.summary,
            evidence=args.evidence,
            review_type=args.review_type,
        )
        _write_json(result, output) if json_output else print(
            f"Recorded checkpoint {result['checkpoint_id']}", file=output
        )
        return 0

    raise AssertionError(f"Unhandled governance command: {args.command}")


def _write_json(payload: object, output: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
