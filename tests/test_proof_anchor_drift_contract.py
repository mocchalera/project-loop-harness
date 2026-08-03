from __future__ import annotations

from copy import deepcopy
import json

from pcl.contracts.proof_anchor_drift import (
    DRIFT_EFFECTS,
    DRIFT_HARD_ERROR_CODES,
    DRIFT_REASON_CODES,
    eligibility_sha256,
    finalize_proof_anchor_drift_eligibility,
    proof_anchor_drift_eligibility_schema,
    subject_sha256,
    validate_proof_anchor_drift_eligibility,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
EVENT_A = "EV-" + "A" * 64


def _receipt() -> dict:
    subject = {
        "contract_version": "proof-anchor-drift-subject/v1",
        "project_instance_id": "project-1",
        "target": {"type": "task", "id": "T-0001"},
        "candidate": {
            "object_format": "sha1",
            "commit_oid": "1" * 40,
            "tree_oid": "2" * 40,
        },
        "expected_basis_sha256": SHA_A,
        "anchor_event_id": EVENT_A,
        "requested_use": "drift_eligibility_predicate",
        "subject_sha256": SHA_B,
    }
    subject["subject_sha256"] = subject_sha256(subject)
    return finalize_proof_anchor_drift_eligibility(
        {
            "contract_version": "proof-anchor-drift-eligibility/v1",
            "subject": subject,
            "anchor": {
                "event_id": EVENT_A,
                "event_sequence": 1,
                "request_id": "PA-" + "B" * 64,
                "base_request_sha256": SHA_A,
                "anchor_generation": 0,
                "basis_sha256": SHA_A,
                "anchor_sha256": SHA_B,
                "manifest_file_sha256": SHA_A,
                "evidence_id": "E-0001",
                "health_status": "healthy",
                "chain_head": True,
            },
            "observation": {
                "snapshot": {
                    "schema_version": 8,
                    "evaluated_through_event_sequence": 1,
                    "evaluated_through_event_id": EVENT_A,
                },
                "chain": {
                    "valid_chain_count": 1,
                    "malformed_group_present": False,
                    "tombstone_status": "absent",
                    "tombstone_event_id": None,
                    "exhaustion_witness_status": "absent",
                    "selected_head_event_id": EVENT_A,
                    "selected_head_generation": 0,
                },
                "stored": {
                    "basis_document_status": "valid",
                    "authorization_documents_status": "valid",
                    "recorded_actor_independence": "matched",
                    "anchor_authorization_granted": True,
                    "issuer_capability_validation": "write_time_only_not_reconstituted",
                },
                "live": {
                    "reconstruction_status": "matched",
                    "basis_sha256": SHA_A,
                    "policy_sha256": SHA_A,
                    "coverage_group_sha256": SHA_A,
                    "admission_sha256": SHA_A,
                    "current_proof_sha256": SHA_A,
                    "authority_surface_resolution_sha256": SHA_A,
                },
            },
            "eligibility": {
                "status": "eligible",
                "predicate_kind": "drift_eligibility_only",
                "matched": True,
                "direct_input_right": False,
                "check_skip_authorized": False,
                "result_substitution_authorized": False,
            },
            "reason_codes": [],
            "authorization_status": {
                "independent_review": "pending",
                "human_gate": "not_required",
                "anchoring_authorized": False,
                "reuse_authorized": False,
                "terminal_authority": False,
                "mandatory_evidence": False,
            },
            "handoff": {
                "status": "anchored_candidate",
                "reuse_consumable": False,
                "terminal_consumable": False,
                "promotion_authorized": False,
            },
            "effects": dict(DRIFT_EFFECTS),
            "eligibility_sha256": SHA_B,
        }
    )


def test_contract_digest_schema_and_closed_vocabularies() -> None:
    receipt = _receipt()
    assert validate_proof_anchor_drift_eligibility(receipt).ok
    assert receipt["eligibility_sha256"] == eligibility_sha256(receipt)
    assert len(DRIFT_REASON_CODES) == 22
    assert tuple(sorted(DRIFT_REASON_CODES)) == DRIFT_REASON_CODES
    assert len(DRIFT_HARD_ERROR_CODES) == 13

    schema = proof_anchor_drift_eligibility_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def assert_closed(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" or "properties" in value:
                assert value.get("additionalProperties") is False
            for nested in value.values():
                assert_closed(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_closed(nested)

    assert_closed(schema)


def test_contract_rejects_unknowns_rights_digest_nullability_nan_and_caps() -> None:
    receipt = _receipt()
    mutants: list[dict] = []

    unknown = deepcopy(receipt)
    unknown["eligibility"]["future_right"] = True
    mutants.append(unknown)

    right = deepcopy(receipt)
    right["eligibility"]["check_skip_authorized"] = True
    mutants.append(right)

    digest = deepcopy(receipt)
    digest["subject"]["target"]["id"] = "T-0002"
    mutants.append(digest)

    invalid_null = deepcopy(receipt)
    invalid_null["observation"]["chain"]["valid_chain_count"] = None
    mutants.append(invalid_null)

    nan_value = deepcopy(receipt)
    nan_value["observation"]["snapshot"]["evaluated_through_event_sequence"] = float("nan")
    mutants.append(nan_value)

    cap = deepcopy(receipt)
    cap["subject"]["target"]["id"] = "T" * 4097
    mutants.append(cap)

    secret = deepcopy(receipt)
    secret["subject"]["target"]["id"] = "token=0123456789abcdef0123456789abcdef"
    mutants.append(secret)

    for mutant in mutants:
        assert not validate_proof_anchor_drift_eligibility(mutant).ok


def test_valid_tombstone_has_null_chain_fields_and_never_grants_rights() -> None:
    receipt = _receipt()
    receipt["anchor"]["health_status"] = "postcommit_unhealthy"
    receipt["anchor"]["chain_head"] = None
    receipt["observation"]["chain"].update(
        {
            "valid_chain_count": None,
            "malformed_group_present": None,
            "tombstone_status": "valid",
            "tombstone_event_id": "EV-" + "C" * 64,
            "exhaustion_witness_status": "present",
        }
    )
    receipt["observation"]["stored"].update(
        {
            "basis_document_status": "unavailable",
            "authorization_documents_status": "unavailable",
            "recorded_actor_independence": "not_observed",
            "anchor_authorization_granted": None,
        }
    )
    receipt["observation"]["live"] = {
        key: ("not_run" if key == "reconstruction_status" else None)
        for key in receipt["observation"]["live"]
    }
    receipt["eligibility"].update({"status": "unavailable", "matched": False})
    receipt["reason_codes"] = ["anchor_exhaustion_tombstoned"]
    receipt["authorization_status"] = None
    receipt["handoff"] = None
    finalized = finalize_proof_anchor_drift_eligibility(receipt)
    assert validate_proof_anchor_drift_eligibility(finalized).ok
    assert finalized["anchor"]["chain_head"] is None
    assert all(
        finalized["eligibility"][field] is False
        for field in (
            "direct_input_right",
            "check_skip_authorized",
            "result_substitution_authorized",
        )
    )
    json.dumps(finalized, allow_nan=False)
