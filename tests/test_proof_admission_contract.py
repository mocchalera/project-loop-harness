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
        "missing": ["participant_without_required_role", "required_role_missing"],
        "not_run": ["required_role_not_run"],
        "executed": [],
    }[attempt]
    state = {
        "missing": "invalid",
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


def _launder_to_reviewable(admission: dict) -> dict:
    admission = deepcopy(admission)
    admission["state_reason_codes"] = []
    admission["admission_state"] = "reviewable"
    admission["review_readiness"] = "ready"
    admission["promotion_suitability"] = "candidate"
    return finalize_proof_coverage_admission(admission)


def _as_canary(admission: dict) -> dict:
    admission = deepcopy(admission)
    observation = admission["role_observations"][0]
    observation.update(
        {
            "role": "authority_canary.rank-canary",
            "kind": "authority_canary",
            "canary_id": "rank-canary",
            "selector_audit_status": "matched",
            "effect_status": "satisfied",
        }
    )
    admission["role_observations"][0] = finalize_proof_coverage_observation(
        observation
    )
    return admission


def _replace_single_participant(admission: dict, participant: dict) -> dict:
    admission = deepcopy(admission)
    observation = admission["role_observations"][0]
    observation["matching_checks"] = [
        {
            "participant_sha256": participant["participant_sha256"],
            "check_id": observation["check_id"],
        }
    ]
    observation["selected_participant_sha256"] = participant[
        "participant_sha256"
    ]
    observation["aggregate_verdict"] = participant["aggregate_verdict"]
    observation["aggregate_reuse_disposition"] = participant[
        "aggregate_reuse_disposition"
    ]
    observation["aggregate_anchoring_eligible"] = participant[
        "aggregate_anchoring_eligible"
    ]
    observation["aggregate_positive_proof_handoff"] = participant[
        "aggregate_positive_proof_handoff"
    ]
    observation["output_commitment_status"] = participant[
        "aggregate_output_commitment_status"
    ]
    admission["participants"] = [participant]
    admission["role_observations"][0] = finalize_proof_coverage_observation(
        observation
    )
    return admission


def _participant_variant(*, verdict: str = "passed", nonce: int = 1) -> dict:
    participant = _participant()
    participant["aggregate_verdict"] = verdict
    participant["bundle_sha256"] = f"sha256:{nonce:064x}"
    participant["proof_key_sha256"] = f"sha256:{nonce + 4096:064x}"
    return finalize_proof_coverage_participant(participant)


def _admission_with_participants(
    participants: list[dict],
    *,
    matching_digests: set[str],
) -> dict:
    admission = _admission("executed")
    participants = sorted(participants, key=lambda item: item["participant_sha256"])
    matching = sorted(
        (
            {
                "participant_sha256": participant["participant_sha256"],
                "check_id": f"check-{index:04d}",
            }
            for index, participant in enumerate(participants)
            if participant["participant_sha256"] in matching_digests
        ),
        key=lambda item: (item["participant_sha256"], item["check_id"]),
    )
    assert matching
    selected = matching[0]
    selected_participant = next(
        participant
        for participant in participants
        if participant["participant_sha256"] == selected["participant_sha256"]
    )
    observation = admission["role_observations"][0]
    observation["matching_checks"] = matching
    observation["selected_participant_sha256"] = selected["participant_sha256"]
    observation["check_id"] = selected["check_id"]
    observation["aggregate_verdict"] = selected_participant["aggregate_verdict"]
    observation["aggregate_reuse_disposition"] = selected_participant[
        "aggregate_reuse_disposition"
    ]
    observation["aggregate_anchoring_eligible"] = selected_participant[
        "aggregate_anchoring_eligible"
    ]
    observation["aggregate_positive_proof_handoff"] = selected_participant[
        "aggregate_positive_proof_handoff"
    ]
    observation["output_commitment_status"] = selected_participant[
        "aggregate_output_commitment_status"
    ]
    admission["participants"] = participants
    admission["role_observations"][0] = finalize_proof_coverage_observation(
        observation
    )
    return admission


def _reviewer_medium_3_case(case: str) -> tuple[dict, str]:
    if case == "attempt_missing":
        return _launder_to_reviewable(_admission("missing")), "required_role_missing"
    if case == "attempt_not_run":
        return _launder_to_reviewable(_admission("not_run")), "required_role_not_run"
    if case.startswith("aggregate_"):
        verdict = case.removeprefix("aggregate_")
        participant = _participant_variant(verdict=verdict)
        admission = _replace_single_participant(_admission("executed"), participant)
        return _launder_to_reviewable(admission), f"participant_aggregate_{verdict}"

    admission = _admission("executed")
    field: str
    value: str
    expected: str
    if case.startswith("selector_"):
        admission = _as_canary(admission)
        field = "selector_audit_status"
        value = case.removeprefix("selector_")
        expected = (
            "canary_plan_mismatch"
            if value == "mismatched"
            else "selector_audit_status"
        )
    elif case.startswith("effect_"):
        admission = _as_canary(admission)
        field = "effect_status"
        value = case.removeprefix("effect_")
        expected = {
            "mismatched": "canary_effect_mismatch",
            "unsupported": "canary_effect_expectation_unsupported",
            "unproved": "canary_pcl_state_effect_unproved",
            "not_observed": "effect_status",
        }[value]
    elif case.startswith("blob_"):
        field = "candidate_blob_status"
        value = case.removeprefix("blob_")
        expected = {
            "oid_mismatch": "candidate_blob_oid_mismatch",
            "missing": "candidate_blob_missing",
            "unsupported_type": "candidate_blob_type_unsupported",
            "indeterminate": "candidate_blob_resolution_indeterminate",
        }[value]
    else:
        assert case == "plan_mismatched"
        field = "plan_binding_status"
        value = "mismatched"
        expected = "participant_policy_mismatch"
    observation = admission["role_observations"][0]
    observation[field] = value
    admission["role_observations"][0] = finalize_proof_coverage_observation(
        observation
    )
    return _launder_to_reviewable(admission), expected


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


@pytest.mark.parametrize(
    "case",
    [
        "plan_mismatched",
        "selector_mismatched",
        "blob_oid_mismatch",
        "blob_missing",
        "blob_indeterminate",
        "effect_mismatched",
        "effect_unsupported",
        "effect_unproved",
        "selector_not_observed",
        "effect_not_observed",
        "attempt_not_run",
        "aggregate_failed",
        "aggregate_blocked",
        "aggregate_timed_out",
        "aggregate_cancelled",
        "aggregate_spawn_failed",
    ],
)
def test_reviewer_medium_3_conditions_cannot_be_laundered_to_reviewable(
    case: str,
) -> None:
    admission, expected_error = _reviewer_medium_3_case(case)

    validation = validate_proof_coverage_admission(admission)

    assert admission["admission_state"] == "reviewable"
    assert not validation.ok
    assert any(expected_error in error for error in validation.errors)


@pytest.mark.parametrize(
    "case",
    [
        "attempt_missing",
        "blob_unsupported_type",
        "aggregate_invalid",
        "aggregate_indeterminate",
    ],
)
def test_remaining_observation_and_aggregate_reason_edges_are_total(
    case: str,
) -> None:
    admission, expected_error = _reviewer_medium_3_case(case)

    validation = validate_proof_coverage_admission(admission)

    assert not validation.ok
    assert any(expected_error in error for error in validation.errors)


@pytest.mark.parametrize(
    "condition",
    [
        "coverage_group_mismatch",
        "duplicate_bundle",
        "duplicate_proof_key",
        "duplicate_required_role",
        "participant_without_required_role",
    ],
)
def test_structural_reason_edges_cannot_be_laundered_to_reviewable(
    condition: str,
) -> None:
    first = _participant_variant(nonce=101)
    second = _participant_variant(nonce=202)
    if condition == "coverage_group_mismatch":
        first = deepcopy(first)
        first["participant_group_sha256"] = f"sha256:{303:064x}"
        first = finalize_proof_coverage_participant(first)
        admission = _replace_single_participant(_admission("executed"), first)
    elif condition == "duplicate_bundle":
        second = deepcopy(second)
        second["bundle_sha256"] = first["bundle_sha256"]
        second = finalize_proof_coverage_participant(second)
        admission = _admission_with_participants(
            [first, second],
            matching_digests={first["participant_sha256"]},
        )
    elif condition == "duplicate_proof_key":
        second = deepcopy(second)
        second["proof_key_sha256"] = first["proof_key_sha256"]
        second = finalize_proof_coverage_participant(second)
        admission = _admission_with_participants(
            [first, second],
            matching_digests={first["participant_sha256"]},
        )
    elif condition == "duplicate_required_role":
        admission = _admission_with_participants(
            [first, second],
            matching_digests={
                first["participant_sha256"],
                second["participant_sha256"],
            },
        )
    else:
        admission = _admission_with_participants(
            [first, second],
            matching_digests={first["participant_sha256"]},
        )
    admission = _launder_to_reviewable(admission)

    validation = validate_proof_coverage_admission(admission)

    assert not validation.ok
    assert any(condition in error for error in validation.errors)


def test_unselected_duplicate_adverse_fact_and_input_permutation_cannot_hide_reason(
) -> None:
    healthy_candidates = [
        _participant_variant(verdict="passed", nonce=1000 + index)
        for index in range(32)
    ]
    adverse_candidates = [
        _participant_variant(verdict="failed", nonce=2000 + index)
        for index in range(32)
    ]
    pair = next(
        (
            (healthy, adverse)
            for healthy in healthy_candidates
            for adverse in adverse_candidates
            if healthy["participant_sha256"] < adverse["participant_sha256"]
        ),
        None,
    )
    assert pair is not None
    healthy, adverse = pair
    matching = {healthy["participant_sha256"], adverse["participant_sha256"]}

    forward = _launder_to_reviewable(
        _admission_with_participants(
            [healthy, adverse],
            matching_digests=matching,
        )
    )
    reverse = _launder_to_reviewable(
        _admission_with_participants(
            [adverse, healthy],
            matching_digests=matching,
        )
    )

    assert forward == reverse
    assert forward["role_observations"][0]["selected_participant_sha256"] == healthy[
        "participant_sha256"
    ]
    for admission in (forward, reverse):
        validation = validate_proof_coverage_admission(admission)
        assert not validation.ok
        assert any(
            "duplicate_required_role" in error for error in validation.errors
        )
        assert any(
            "participant_aggregate_failed" in error
            for error in validation.errors
        )


def test_all_true_reason_edges_survive_rank_precedence() -> None:
    participant = _participant_variant(verdict="failed", nonce=3001)
    admission = _replace_single_participant(_admission("not_run"), participant)
    observation = admission["role_observations"][0]
    observation["plan_binding_status"] = "mismatched"
    admission["role_observations"][0] = finalize_proof_coverage_observation(
        observation
    )
    admission["state_reason_codes"] = [
        "participant_aggregate_failed",
        "participant_policy_mismatch",
        "required_role_not_run",
    ]
    admission["admission_state"] = "invalid"
    admission["review_readiness"] = "withheld"
    admission["promotion_suitability"] = "withheld"
    admission = finalize_proof_coverage_admission(admission)

    assert validate_proof_coverage_admission(admission).ok


def test_nonserialized_authority_reason_remains_a_valid_declared_fact() -> None:
    admission = _admission("executed")
    admission["state_reason_codes"] = ["authority_current_mismatch"]
    admission["admission_state"] = "stale"
    admission["review_readiness"] = "withheld"
    admission["promotion_suitability"] = "withheld"
    admission = finalize_proof_coverage_admission(admission)

    assert validate_proof_coverage_admission(admission).ok


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
