from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .adaptive_policy import render_policy_explanation, resolve_policy_for_target
from .completion_policies import evaluate_completion_policy
from .contracts.claim_set import (
    CLAIM_SET_CONTRACT_VERSION,
    load_claim_set,
    validate_claim_set,
)
from .contracts.completion_packet import (
    COMPLETION_PACKET_CONTRACT_VERSION,
    load_completion_packet,
    validate_completion_packet,
)
from .contracts.completion_policy import (
    COMPLETION_POLICY_CONTRACT_VERSION,
    load_completion_policy,
    validate_completion_policy,
)
from .contracts.council_run import (
    COUNCIL_RUN_CONTRACT_VERSION,
    load_council_run,
    validate_council_run,
)
from .contracts.decision_proposal import (
    DECISION_PROPOSAL_CONTRACT_VERSION,
    load_decision_proposal,
    validate_decision_proposal,
)
from .contracts.evidence_set import (
    EVIDENCE_SET_CONTRACT_VERSION,
    load_evidence_set,
    validate_evidence_set,
)
from .contracts.gap_report import (
    GAP_REPORT_CONTRACT_VERSION,
    load_gap_report,
    validate_gap_report,
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
from .contracts.profile_manifest import (
    PROFILE_MANIFEST_CONTRACT_VERSION,
    load_profile_manifest,
    validate_profile_manifest,
)
from .contracts.profile_output_bundle import (
    PROFILE_OUTPUT_BUNDLE_CONTRACT_VERSION,
    load_profile_output_bundle,
    validate_profile_output_bundle,
)
from .contracts.profile_run_request import (
    PROFILE_RUN_REQUEST_CONTRACT_VERSION,
    load_profile_run_request,
    validate_profile_run_request,
)
from .contracts.route_override import (
    ROUTE_OVERRIDE_CONTRACT_VERSION,
    load_route_override,
    validate_route_override,
)
from .contracts.route_recommendation import (
    ROUTE_RECOMMENDATION_CONTRACT_VERSION,
    load_route_recommendation,
    validate_route_recommendation,
)
from .contracts.verification_plan import (
    VERIFICATION_PLAN_CONTRACT_VERSION,
    load_verification_plan,
    validate_verification_plan,
)
from .contracts.work_brief import (
    WORK_BRIEF_CONTRACT_VERSION,
    load_work_brief,
    validate_work_brief,
)
from .errors import InvalidInputError
from .evidence_sets import plan_evidence_set, record_evidence_set, show_evidence_set
from .gap_reports import add_gap_report, list_gap_reports, promote_gap_lesson, show_gap_report
from .paths import ProjectPaths
from .presentation import to_pretty_json
from .profile_authorization import (
    ProfileAuthorizationError,
    authorize_profile_request,
    revoke_profile_authorization,
)
from .profile_bundle_store import ingest_profile_bundle
from .profile_fixture_runner import run_profile_fixture
from .profile_ingest import plan_profile_ingest
from .profile_prepare import prepare_profile_request
from .profiles import list_profiles, show_profile, validate_profile
from .resume import build_handoff_packet, render_handoff_markdown, serialized_handoff_packet
from .route_overrides import current_route, override_route
from .routing import recommend_route
from .work_briefs import add_work_brief, approve_work_brief, review_work_brief, show_work_brief


PROFILE_COMMANDS = frozenset(
    {"profile", "contract", "evidence-set", "completion", "brief", "gap", "route", "policy", "resume"}
)


def handle_profile_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
) -> int | None:
    """Handle profile, contract, work-input, and routing commands."""

    if args.command not in PROFILE_COMMANDS:
        return None

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
            print(f"Source: {result['source']} trust={result['trust']} executed_by_plh=false")
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
        _print_json(result) if json_output else print(to_pretty_json(result))
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
        _print_json(result) if json_output else print(to_pretty_json(result))
        return 0

    if args.command == "profile" and args.profile_command == "fixture-run":
        result = run_profile_fixture(
            request_file=args.request_file,
            status=args.status,
            output_dir=args.output_dir,
        )
        _print_json(result) if json_output else print(to_pretty_json(result))
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
        _print_json(result) if json_output else print(to_pretty_json(result["evidence_set"]))
        return 0

    if args.command == "completion" and args.completion_command == "evaluate":
        result = evaluate_completion_policy(
            paths,
            policy_file=args.policy_file,
            evidence_set_id=args.evidence_set_id,
            test_case_id=args.test_case_id,
        )
        _print_json(result) if json_output else print(to_pretty_json(result["evaluation"]))
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
        _print_json(result) if json_output else print(to_pretty_json(result))
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
        result = add_gap_report(paths, file=args.file, summary=args.summary, dry_run=args.dry_run)
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
        _print_json(result) if json_output else print(to_pretty_json(result))
        return 0

    if args.command == "gap" and args.gap_command == "list":
        result = list_gap_reports(
            paths,
            target_ref=args.target_ref,
            gap_class=args.gap_class,
        )
        _print_json(result) if json_output else print(to_pretty_json(result))
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
            print(f"Approved candidate lesson {args.lesson_id}; durable-owner application pending")
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
                f"{result['evidence']['id']} {result['recommendation']['profile']} "
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
        _print_json(result) if json_output else print(to_pretty_json(result))
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

    return None


def _validate_contract_file(
    path_value: str,
    *,
    contract_type: str,
    json_output: bool,
) -> int:
    contract_handlers = {
        COMPLETION_PACKET_CONTRACT_VERSION: (load_completion_packet, validate_completion_packet),
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
        COMPLETION_POLICY_CONTRACT_VERSION: (load_completion_policy, validate_completion_policy),
        PROFILE_MANIFEST_CONTRACT_VERSION: (load_profile_manifest, validate_profile_manifest),
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


def _print_evidence_set_warnings(result: dict) -> None:
    for warning in result.get("warnings", []):
        print(
            "WARNING: Evidence set excluded "
            f"{warning['kind']} ({warning['status']}) at {warning['path']}; "
            f"required={str(warning['required']).lower()}.",
            file=sys.stderr,
        )


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
