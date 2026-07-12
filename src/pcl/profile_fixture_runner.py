from __future__ import annotations

import hashlib
from datetime import datetime
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

from .contracts._profile_contract import canonical_json, load_strict_json
from .contracts.claim_set import validate_claim_set
from .contracts.council_run import validate_council_run
from .contracts.decision_proposal import validate_decision_proposal
from .contracts.profile_output_bundle import bundle_digest, validate_profile_output_bundle
from .contracts.profile_run_request import validate_profile_run_request
from .contracts.verification_plan import validate_verification_plan
from .errors import EXIT_USAGE, PclError


PROFILE_FIXTURE_RUN_RESULT_VERSION = "profile-fixture-run-result/v1"


class ProfileFixtureError(PclError):
    pass


def run_profile_fixture(
    *,
    request_file: str,
    status: str,
    output_dir: str,
) -> dict[str, Any]:
    request = load_strict_json(request_file)
    validation = validate_profile_run_request(request)
    if not validation.ok or not isinstance(request, dict):
        raise _error(
            "profile_fixture_request_invalid",
            "Fixture runner requires a valid profile-run-request/v1.",
            errors=list(validation.errors),
        )
    if (
        request["data_policy"]["network_access"] != "forbidden"
        or request["data_policy"]["paid_service_requested"] is not False
        or request["authorization"] is not None
    ):
        raise _error(
            "profile_fixture_offline_only",
            "Fixture runner accepts offline, non-paid, unauthorized requests only.",
        )
    scenarios = _scenarios()
    scenario = next((item for item in scenarios if item["name"] == status), None)
    if scenario is None:
        raise _error(
            "profile_fixture_status_invalid",
            f"Unknown fixture status: {status}",
            allowed=[item["name"] for item in scenarios],
        )
    bundle_status = str(scenario["bundle_status"])
    seed = hashlib.sha256(
        f"{request['request_id']}:{request['request_digest']['value']}:{status}".encode()
    ).hexdigest()
    timestamp = str(request["generated_at"])
    compact_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    run_id = f"CR-{compact_time}-{seed[:8]}"
    request_ref = {
        "request_id": request["request_id"],
        "request_digest": request["request_digest"]["value"],
    }
    run = _run_artifact(run_id, request_ref, bundle_status, timestamp, seed)
    claims = _claims_artifact(run_id)
    verification = _verification_artifact(run_id)
    artifacts: list[tuple[str, str, str, str, dict[str, Any]]] = [
        ("A-001", "run_manifest", "council-run/v0", "council-run.json", run),
        ("A-002", "claims", "claim-set/v0", "claim-set.json", claims),
        (
            "A-003",
            "verification_plan",
            "verification-plan/v0",
            "verification-plan.json",
            verification,
        ),
    ]
    if bundle_status == "needs_human":
        proposal = _decision_artifact(run_id, request["target"])
        artifacts.append(
            (
                "A-004",
                "decision_proposal",
                "decision-proposal/v0",
                "decision-proposal.json",
                proposal,
            )
        )
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_artifacts = []
    for artifact_id, role, contract, name, value in artifacts:
        _validate_artifact(contract, value)
        path = directory / name
        data = _json_bytes(value)
        path.write_bytes(data)
        manifest_artifacts.append(
            {
                "artifact_id": artifact_id,
                "role": role,
                "contract_version": contract,
                "path": name,
                "media_type": "application/json",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    next_action = _next_action(bundle_status)
    bundle: dict[str, Any] = {
        "contract_version": "profile-output-bundle/v1",
        "bundle_id": f"POB-{compact_time}-{seed[8:16]}",
        "generated_at": timestamp,
        "request_ref": request_ref,
        "profile": request["profile"],
        "status": bundle_status,
        "summary": f"Deterministic offline fixture: {status}",
        "artifacts": manifest_artifacts,
        "decision_proposal_artifact_ids": ["A-004"] if bundle_status == "needs_human" else [],
        "next_action": next_action,
    }
    bundle["bundle_digest"] = {
        "algorithm": "sha256",
        "canonicalization": "pcl-canonical-json/v1-excluding-bundle_digest",
        "value": bundle_digest(bundle),
    }
    bundle_validation = validate_profile_output_bundle(bundle)
    if not bundle_validation.ok:
        raise _error(
            "profile_fixture_internal_invalid",
            "Generated fixture bundle failed validation.",
            errors=list(bundle_validation.errors),
        )
    if scenario.get("malformed") is True:
        bundle["artifacts"][0]["sha256"] = "0" * 64
        bundle["bundle_digest"]["value"] = bundle_digest(bundle)
    bundle_path = directory / "profile-output-bundle.json"
    bundle_path.write_bytes(_json_bytes(bundle))
    return {
        "contract_version": PROFILE_FIXTURE_RUN_RESULT_VERSION,
        "ok": True,
        "runner_profile_id": "council.discovery",
        "fixture_status": status,
        "provider_code_present": False,
        "network_used": False,
        "paid_service_used": False,
        "plh_state_mutated": False,
        "bundle_path": str(bundle_path),
        "bundle_id": bundle["bundle_id"],
        "bundle_digest": bundle["bundle_digest"]["value"],
    }


def _scenarios() -> list[dict[str, Any]]:
    value = json.loads(
        files("pcl")
        .joinpath("profiles/fixtures/council.discovery/scenarios.json")
        .read_text(encoding="utf-8")
    )
    return list(value["scenarios"])


def _run_artifact(
    run_id: str,
    request_ref: dict[str, str],
    status: str,
    timestamp: str,
    seed: str,
) -> dict[str, Any]:
    stop_reason = {
        "completed": "criteria_satisfied",
        "needs_human": "human_decision_required",
        "partial": "wall_time_exhausted",
        "budget_exhausted": "budget_exhausted",
        "failed": "runner_error",
        "skipped": "policy_skip",
    }[status]
    return {
        "contract_version": "council-run/v0",
        "run_id": run_id,
        "request_ref": request_ref,
        "orchestrator": {
            "name": "pcl-offline-fixture",
            "version": "1",
            "policy_id": "fixture",
            "policy_version": "1",
        },
        "topology": "single",
        "selection_rationale": "Deterministic offline contract fixture with no provider.",
        "participants": [
            {
                "participant_id": "P-01",
                "role": "generalist",
                "provider": "offline-fixture",
                "model_id_requested": "none",
                "model_id_reported": None,
                "model_revision": None,
                "pinning_status": "exact",
                "settings": {
                    "reasoning_effort": "default",
                    "temperature": None,
                    "max_output_tokens": 1,
                },
                "context_isolation": "independent_first_pass",
                "prompt_sha256": seed,
            }
        ],
        "rounds": [
            {
                "round": 1,
                "purpose": "independent_proposal",
                "participant_ids": ["P-01"],
                "output_sha256": hashlib.sha256(f"round:{seed}".encode()).hexdigest(),
            }
        ],
        "budget": {
            "token_limit": 1,
            "actual_input_tokens": 0,
            "actual_output_tokens": 0,
            "monetary_limit": None,
            "actual_cost": 0,
            "currency": None,
            "cost_is_estimated": False,
        },
        "privacy": {
            "external_network_used": False,
            "providers_used": [],
            "repository_content_sent": "none",
            "sensitive_content_sent": False,
            "secret_scan_performed": True,
        },
        "stop": {
            "reason": stop_reason,
            "criteria_met": status == "completed",
            "unresolved_high_severity_claims": 1 if status == "needs_human" else 0,
            "new_high_severity_findings_last_round": 0,
        },
        "status": status,
        "started_at": timestamp,
        "completed_at": timestamp,
    }


def _claims_artifact(run_id: str) -> dict[str, Any]:
    return {
        "contract_version": "claim-set/v0",
        "claim_set_id": "CS-0001",
        "run_ref": run_id,
        "claims": [
            {
                "claim_id": "C-001",
                "kind": "assumption",
                "statement": "Offline fixture claim; not promoted to fact or approval.",
                "severity": "medium",
                "confidence_band": "not_applicable",
                "status": "requires_human",
                "source_participant_ids": ["P-01"],
                "evidence_refs": [],
                "conditions": ["Fixture output is contract-test data only"],
                "impact": "Exercises Evidence boundaries.",
                "reversibility": "easy",
                "verification_item_refs": ["VP-001"],
                "challenge_summary": None,
            }
        ],
    }


def _verification_artifact(run_id: str) -> dict[str, Any]:
    return {
        "contract_version": "verification-plan/v0",
        "verification_plan_id": "VPL-0001",
        "run_ref": run_id,
        "execution_policy": "proposal_only_never_auto_execute",
        "items": [
            {
                "verification_item_id": "VP-001",
                "claim_refs": ["C-001"],
                "method": "deterministic_check",
                "description": "Confirm fixture artifacts remain inert Evidence.",
                "proposed_commands": ["echo fixture-command-must-not-run"],
                "preconditions": ["Human explicitly chooses to verify"],
                "requires_human_approval": False,
                "safety_class": "read_only",
                "expected_artifacts": ["Explicit verification result"],
                "pass_condition": "A separate verifier records a result.",
                "failure_meaning": "Fixture output remains unverified.",
                "estimated_effort": "small",
                "status": "proposed",
            }
        ],
    }


def _decision_artifact(run_id: str, target: dict[str, str]) -> dict[str, Any]:
    candidates = []
    for candidate_id, title in (("OPT-A", "Keep the bounded path"), ("OPT-B", "Revise the Brief")):
        candidates.append(
            {
                "candidate_id": candidate_id,
                "title": title,
                "summary": f"Offline fixture candidate {candidate_id}.",
                "benefits": ["Exercises human governance"],
                "costs": ["Requires an explicit human choice"],
                "risks": ["Fixture only; no production claim"],
                "assumptions": ["Human recognizes fixture context"],
                "evidence_refs": ["C-001", "VP-001"],
                "uncertainty": "medium",
                "reversibility": "easy",
                "reconsider_when": ["The Work Brief changes"],
            }
        )
    return {
        "contract_version": "decision-proposal/v0",
        "proposal_id": "DP-0001",
        "run_ref": run_id,
        "target": target,
        "question": "Which bounded fixture candidate should be selected?",
        "why_human_required": "A recommendation cannot authorize its own selection.",
        "impact_scope": "Fixture Decision state only.",
        "candidates": candidates,
        "recommended_candidate_id": "OPT-A",
        "recommendation_reason": "OPT-A is the minimal bounded fixture path.",
        "unanswered_behavior": "block",
        "unresolved_assumptions": ["Human selection is still required"],
        "minority_opinions": [],
        "generated_by": {"run_ref": run_id, "participant_ids": ["P-01"]},
    }


def _next_action(status: str) -> dict[str, Any]:
    kind = {
        "completed": "none",
        "needs_human": "human_decision",
        "partial": "revise_work_brief",
        "budget_exhausted": "revise_work_brief",
        "failed": "inspect_failure",
        "skipped": "none",
    }[status]
    return {
        "kind": kind,
        "requires_human": status in {"needs_human", "partial", "budget_exhausted", "failed"},
        "safe_to_run": False,
        "summary": f"Offline fixture safe next action for {status}.",
    }


def _validate_artifact(contract: str, value: dict[str, Any]) -> None:
    validator = {
        "council-run/v0": validate_council_run,
        "claim-set/v0": validate_claim_set,
        "verification-plan/v0": validate_verification_plan,
        "decision-proposal/v0": validate_decision_proposal,
    }[contract]
    result = validator(value)
    if not result.ok:
        raise _error(
            "profile_fixture_internal_invalid",
            f"Generated {contract} failed validation.",
            errors=list(result.errors),
        )


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _error(code: str, message: str, **details: Any) -> ProfileFixtureError:
    return ProfileFixtureError(
        message=message,
        code=code,
        exit_code=EXIT_USAGE,
        details=details,
    )
