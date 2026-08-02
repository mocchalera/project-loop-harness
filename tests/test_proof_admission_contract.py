from __future__ import annotations

from copy import deepcopy
import json

import pytest

from pcl.contracts.proof_admission import (
    EFFECTS_ZERO,
    PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION,
    PROOF_COVERAGE_POLICY_CONTRACT_VERSION,
    canary_item_sha256,
    derive_current_proof_match_status,
    derive_effect_status,
    derive_role_freshness,
    finalize_proof_coverage_admission,
    finalize_proof_coverage_observation,
    finalize_proof_coverage_participant,
    finalize_proof_coverage_policy,
    proof_coverage_admission_schema,
    proof_coverage_policy_schema,
    validate_proof_coverage_admission,
    validate_proof_coverage_policy,
)


DIGEST = "sha256:" + "a" * 64
OID = "b" * 40


def _check(check_id: str, role: str, *, selectors: list[str] | None = None) -> dict:
    return {
        "check_id": check_id,
        "role": role,
        "argv": ["python", "-m", "pytest"],
        "cwd": ".",
        "selectors": selectors or [],
        "referenced_git_blobs": [{"path": "src/check.py", "oid": OID}],
        "input_ids": [],
        "environment": {
            "inherit_names": ["LANG", "PATH"],
            "workspace_pythonpath": ["src"],
        },
        "timeout_seconds": 60,
        "max_output_bytes": 65_536,
        "declared_outputs": [],
    }


def _execution() -> dict:
    return {
        "plan_sha256": DIGEST,
        "tool_identity_sha256": DIGEST,
        "environment_binding_sha256": DIGEST,
        "public_execution_sha256": DIGEST,
        "spawn_vector_sha256": DIGEST,
        "external_input_binding_sha256": DIGEST,
        "execution_binding_sha256": DIGEST,
    }


def _policy() -> dict:
    canary = {
        "id": "rank-canary",
        "authority_claim_ids": ["C1-rank"],
        "command": ["python", "-m", "pytest"],
        "selectors": ["test_rank"],
        "required_outcome": "pass",
        "referenced_blob_oids": [OID],
        "effect_expectations": ["canonical-product-inputs-unchanged"],
        "supported_platform_conditions": ["python>=3.10"],
    }
    full = _check("full", "full_regression")
    canary_check = _check(
        "canary",
        "authority_canary.rank-canary",
        selectors=["test_rank"],
    )
    return finalize_proof_coverage_policy(
        {
            "contract_version": PROOF_COVERAGE_POLICY_CONTRACT_VERSION,
            "policy_id": "policy-1",
            "producer": {
                "kind": "external_bootstrap",
                "producer_id": "producer-1",
                "producer_sha256": DIGEST,
                "candidate_controlled": False,
            },
            "target": {"type": "task", "id": "T-0001"},
            "candidate": {
                "object_format": "sha1",
                "commit_oid": "c" * 40,
                "tree_oid": "d" * 40,
            },
            "authority_bindings": {
                "authority_surface_resolution_sha256": DIGEST,
                "bootstrap_profile_sha256": DIGEST,
                "canary_union_sha256": DIGEST,
                "isolation_contract_version": "proof-workspace-isolation/v1",
            },
            "coverage_group_sha256": DIGEST,
            "required_roles": [
                {
                    "role": "full_regression",
                    "kind": "full_regression",
                    "canary_id": None,
                    "canary_item_sha256": None,
                    "expected_outcome": "pass",
                    "expected_check": full,
                    "selector_audit_labels": [],
                    "required_candidate_blobs": full["referenced_git_blobs"],
                    "expected_execution": _execution(),
                    "requirement_sha256": DIGEST,
                },
                {
                    "role": "authority_canary.rank-canary",
                    "kind": "authority_canary",
                    "canary_id": "rank-canary",
                    "canary_item_sha256": canary_item_sha256(canary),
                    "expected_outcome": "pass",
                    "expected_check": canary_check,
                    "selector_audit_labels": ["test_rank"],
                    "required_candidate_blobs": canary_check[
                        "referenced_git_blobs"
                    ],
                    "expected_execution": _execution(),
                    "requirement_sha256": DIGEST,
                },
            ],
            "authorization_requirements": {
                "independent_review": "required",
                "human_gate": "required",
                "self_certification_allowed": False,
            },
            "terminal_authority": False,
            "mandatory_evidence": False,
            "policy_sha256": DIGEST,
        }
    )


def _participant() -> dict:
    return finalize_proof_coverage_participant(
        {
            "participant_group_sha256": DIGEST,
            "spec_sha256": DIGEST,
            "workspace_binding_sha256": DIGEST,
            "proof_key_sha256": DIGEST,
            "verification_profile_sha256": DIGEST,
            "check_plan_sha256": DIGEST,
            "external_input_binding_sha256": DIGEST,
            "packet_sha256": DIGEST,
            "executor_contract_sha256": DIGEST,
            "aggregate_sha256": DIGEST,
            "bundle_sha256": DIGEST,
            "aggregate_verdict": "passed",
            "aggregate_output_commitment_status": "committed",
            "aggregate_reuse_disposition": "eligible",
            "aggregate_anchoring_eligible": True,
            "aggregate_positive_proof_handoff": "candidate",
            "aggregate_current_proof": {
                "scope": "not_applicable",
                "status": "not_applicable",
                "proof_sha256": DIGEST,
            },
        }
    )


def _observation(attempt: str, participant: dict) -> dict:
    missing = attempt == "missing"
    executed = attempt == "executed"
    return finalize_proof_coverage_observation(
        {
            "contract_version": "proof-coverage-observation/v1",
            "role": "full_regression",
            "kind": "full_regression",
            "canary_id": None,
            "requirement_sha256": DIGEST,
            "matching_checks": (
                []
                if missing
                else [
                    {
                        "participant_sha256": participant["participant_sha256"],
                        "check_id": "full",
                    }
                ]
            ),
            "selected_participant_sha256": (
                None if missing else participant["participant_sha256"]
            ),
            "check_id": None if missing else "full",
            "attempt_status": attempt,
            "attempt_sha256": DIGEST if executed else None,
            "result_sha256": DIGEST if executed else None,
            "receipt_sha256": DIGEST if executed else None,
            "c3_verdict": "passed" if executed else None,
            "aggregate_verdict": None if missing else "passed",
            "aggregate_reuse_disposition": None if missing else "eligible",
            "aggregate_anchoring_eligible": None if missing else True,
            "aggregate_positive_proof_handoff": None if missing else "candidate",
            "output_commitment_status": None if missing else "committed",
            "plan_binding_status": "not_observed" if missing else "matched",
            "selector_audit_status": "not_applicable",
            "candidate_blob_status": "not_observed" if missing else "matched",
            "candidate_blob_resolution_sha256": None if missing else DIGEST,
            "effect_status": "not_applicable",
            "freshness": "current" if executed else "not_observed",
        }
    )


def _admission(attempt: str) -> dict:
    participant = _participant()
    reasons = {
        "missing": ["required_role_missing"],
        "not_run": ["required_role_not_run"],
        "executed": [],
    }[attempt]
    state = {
        "missing": "incomplete",
        "not_run": "incomplete",
        "executed": "reviewable",
    }[attempt]
    return finalize_proof_coverage_admission(
        {
            "contract_version": PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION,
            "policy_sha256": DIGEST,
            "coverage_group_sha256": DIGEST,
            "participants": [participant],
            "role_observations": [_observation(attempt, participant)],
            "current_proof": {
                "scope": "not_applicable",
                "status": "not_applicable",
                "proof_sha256": DIGEST,
                "match_status": "matched",
            },
            "admission_state": state,
            "state_reason_codes": reasons,
            "review_readiness": "ready" if state == "reviewable" else "withheld",
            "promotion_suitability": (
                "candidate" if state == "reviewable" else "withheld"
            ),
            "promotion_withholding_codes": [],
            "authorization_status": {
                "independent_review": "pending",
                "human_gate": "pending",
                "anchoring_authorized": False,
                "reuse_authorized": False,
                "terminal_authority": False,
                "mandatory_evidence": False,
            },
            "effects": dict(EFFECTS_ZERO),
            "admission_sha256": DIGEST,
        }
    )


def test_c4_contract_modules_and_exact_schema_ids_exist() -> None:
    policy_schema = proof_coverage_policy_schema()
    admission_schema = proof_coverage_admission_schema()
    assert PROOF_COVERAGE_POLICY_CONTRACT_VERSION == "proof-coverage-policy/v1"
    assert PROOF_COVERAGE_ADMISSION_CONTRACT_VERSION == "proof-coverage-admission/v1"
    assert policy_schema["$id"] == (
        "https://project-loop.local/contracts/proof-coverage-policy-v1.schema.json"
    )
    assert admission_schema["$id"] == (
        "https://project-loop.local/contracts/proof-coverage-admission-v1.schema.json"
    )
    assert policy_schema["additionalProperties"] is False
    assert admission_schema["additionalProperties"] is False
    assert json.dumps(policy_schema).count("proof-coverage-policy/v1") >= 1


def test_policy_exact_preimages_and_strict_cross_fields() -> None:
    policy = _policy()
    assert validate_proof_coverage_policy(policy).ok
    for mutate in (
        lambda value: value.update(extra=True),
        lambda value: value["producer"].update(candidate_controlled=True),
        lambda value: value["required_roles"].reverse(),
        lambda value: value["required_roles"][0].update(
            authority_surface_resolution_sha256=DIGEST
        ),
        lambda value: value["required_roles"][1].update(canary_id=None),
        lambda value: value["required_roles"][1].update(
            selector_audit_labels=[]
        ),
        lambda value: value.update(policy_sha256=DIGEST),
    ):
        tampered = deepcopy(policy)
        mutate(tampered)
        assert not validate_proof_coverage_policy(tampered).ok


def test_identifier_and_array_caps_are_exact_and_nonfinite_json_is_rejected() -> None:
    exact = _policy()
    exact["policy_id"] = "a" * 4096
    exact = finalize_proof_coverage_policy(exact)
    assert validate_proof_coverage_policy(exact).ok

    over = deepcopy(exact)
    over["policy_id"] = "a" * 4097
    over = finalize_proof_coverage_policy(over)
    assert not validate_proof_coverage_policy(over).ok

    wrong_type = deepcopy(exact)
    wrong_type["producer"]["kind"] = {"unexpected": True}
    assert not validate_proof_coverage_policy(wrong_type).ok

    nonfinite = deepcopy(exact)
    nonfinite["required_roles"][0]["expected_check"]["timeout_seconds"] = float(
        "nan"
    )
    assert not validate_proof_coverage_policy(nonfinite).ok


@pytest.mark.parametrize("attempt", ["missing", "not_run", "executed"])
def test_output_commitment_status_low_h_nullability_is_explicit(attempt: str) -> None:
    admission = _admission(attempt)
    assert validate_proof_coverage_admission(admission).ok
    observation = admission["role_observations"][0]
    assert (observation["output_commitment_status"] is None) is (
        attempt == "missing"
    )
    tampered = deepcopy(admission)
    tampered_observation = tampered["role_observations"][0]
    tampered_observation["output_commitment_status"] = (
        "committed" if attempt == "missing" else None
    )
    tampered["role_observations"][0] = finalize_proof_coverage_observation(
        tampered_observation
    )
    tampered = finalize_proof_coverage_admission(tampered)
    assert not validate_proof_coverage_admission(tampered).ok


@pytest.mark.parametrize("attempt", ["not_run", "executed"])
@pytest.mark.parametrize(
    "field",
    ["plan_binding_status", "candidate_blob_status"],
)
def test_observed_role_cannot_recompute_not_observed_status_into_reviewable(
    attempt: str,
    field: str,
) -> None:
    admission = _admission(attempt)
    observation = admission["role_observations"][0]
    observation[field] = "not_observed"
    admission["role_observations"][0] = finalize_proof_coverage_observation(
        observation
    )
    admission["state_reason_codes"] = []
    admission["admission_state"] = "reviewable"
    admission["review_readiness"] = "ready"
    admission["promotion_suitability"] = "candidate"
    admission = finalize_proof_coverage_admission(admission)

    validation = validate_proof_coverage_admission(admission)

    assert admission["admission_state"] == "reviewable"
    assert not validation.ok
    assert any(field in error for error in validation.errors)


def test_current_proof_total_functions_cover_every_legal_cartesian_branch() -> None:
    participant_values = {
        "healthy": {"scope": "feature", "status": "healthy", "proof_sha256": DIGEST},
        "unhealthy": {"scope": "feature", "status": "unhealthy", "proof_sha256": DIGEST},
        "not_applicable": {
            "scope": "not_applicable",
            "status": "not_applicable",
            "proof_sha256": DIGEST,
        },
        "changed": {"scope": "feature", "status": "changed", "proof_sha256": DIGEST},
        "indeterminate": {
            "scope": "feature",
            "status": "indeterminate",
            "proof_sha256": None,
        },
    }
    final_values = {
        "healthy": {"scope": "feature", "status": "healthy", "proof_sha256": DIGEST},
        "unhealthy": {"scope": "feature", "status": "unhealthy", "proof_sha256": DIGEST},
        "not_applicable": {
            "scope": "not_applicable",
            "status": "not_applicable",
            "proof_sha256": DIGEST,
        },
        "indeterminate": {
            "scope": "unknown",
            "status": "indeterminate",
            "proof_sha256": None,
        },
    }
    for participant_status, participant_current in participant_values.items():
        for final_status, final in final_values.items():
            participant = _participant()
            participant["aggregate_current_proof"] = participant_current
            if "participant_sha256" in participant:
                participant = finalize_proof_coverage_participant(participant)
            expected = (
                "indeterminate"
                if participant_status == "indeterminate" or final_status == "indeterminate"
                else "mismatched"
                if participant_status == "changed"
                or (
                    participant_current["scope"],
                    participant_current["status"],
                    participant_current["proof_sha256"],
                )
                != (final["scope"], final["status"], final["proof_sha256"])
                else "matched"
            )
            assert derive_current_proof_match_status([participant], final) == expected
            expected_freshness = (
                "indeterminate"
                if participant_status == "indeterminate" or final_status == "indeterminate"
                else "stale"
                if participant_status == "changed" or expected == "mismatched"
                else "current"
            )
            assert (
                derive_role_freshness("executed", participant_current, final)
                == expected_freshness
            )
            assert derive_role_freshness("missing", None, final) == "not_observed"
            assert derive_role_freshness("not_run", None, final) == "not_observed"


def test_effect_total_function_all_branches_and_precedence() -> None:
    assert derive_effect_status(
        kind="authority_canary",
        attempt_status="missing",
        expectations=[],
        canonical_unchanged=False,
        hwm_equality=None,
    ) == "not_observed"
    assert derive_effect_status(
        kind="full_regression",
        attempt_status="executed",
        expectations=["unknown"],
        canonical_unchanged=False,
        hwm_equality=None,
    ) == "not_applicable"
    assert derive_effect_status(
        kind="authority_canary",
        attempt_status="executed",
        expectations=["unknown", "canonical-product-inputs-unchanged"],
        canonical_unchanged=False,
        hwm_equality=None,
    ) == "unsupported"
    assert derive_effect_status(
        kind="authority_canary",
        attempt_status="executed",
        expectations=["canonical-product-inputs-unchanged"],
        canonical_unchanged=False,
        hwm_equality=None,
    ) == "mismatched"
    assert derive_effect_status(
        kind="authority_canary",
        attempt_status="executed",
        expectations=["pcl-state-effect0"],
        canonical_unchanged=True,
        hwm_equality=None,
    ) == "unproved"
    assert derive_effect_status(
        kind="authority_canary",
        attempt_status="executed",
        expectations=["pcl-state-effect0"],
        canonical_unchanged=True,
        hwm_equality=True,
    ) == "not_disproved"
    assert derive_effect_status(
        kind="authority_canary",
        attempt_status="executed",
        expectations=["canonical-product-inputs-unchanged"],
        canonical_unchanged=True,
        hwm_equality=None,
    ) == "satisfied"


def test_admission_digest_annotation_and_effect_tamper_fail_closed() -> None:
    admission = _admission("executed")
    assert validate_proof_coverage_admission(admission).ok
    for mutate in (
        lambda value: value["current_proof"].update(match_status="mismatched"),
        lambda value: value["role_observations"][0].update(freshness="stale"),
        lambda value: value.update(admission_state="invalid"),
        lambda value: value["effects"].update(database_write=1),
        lambda value: value["authorization_status"].update(
            anchoring_authorized=True
        ),
    ):
        tampered = deepcopy(admission)
        mutate(tampered)
        tampered = finalize_proof_coverage_admission(tampered)
        assert not validate_proof_coverage_admission(tampered).ok
