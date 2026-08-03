from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from pcl.contracts.proof_reuse_candidate import (
    PROOF_REUSE_CANDIDATE_CONTRACT_VERSION,
    PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
    REUSE_CANDIDATE_AUTHORIZATION,
    REUSE_CANDIDATE_EFFECTS_SUCCESS,
    REUSE_CANDIDATE_EFFECTS_ZERO,
    REUSE_CANDIDATE_ERROR_PHASES,
    REUSE_CANDIDATE_HANDOFF,
    REUSE_CANDIDATE_HARD_ERROR_CODES,
    REUSE_CANDIDATE_REASON_CODES,
    REUSE_CANDIDATE_REASON_STATUS,
    REUSE_CANDIDATE_STATUS_RANK,
    canonical_proof_reuse_candidate_bytes,
    finalize_proof_reuse_candidate,
    finalize_proof_reuse_candidate_result,
    proof_reuse_candidate_id,
    proof_reuse_candidate_result_schema,
    proof_reuse_candidate_schema,
    proof_reuse_candidate_sha256,
    status_for_reasons,
    validate_proof_reuse_candidate,
    validate_proof_reuse_candidate_result,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
SHA_E = "sha256:" + "e" * 64
SHA_F = "sha256:" + "f" * 64
EVENT_A = "EV-" + "A" * 64
EVENT_B = "EV-" + "B" * 64


def _candidate() -> dict:
    return finalize_proof_reuse_candidate(
        {
            "contract_version": PROOF_REUSE_CANDIDATE_CONTRACT_VERSION,
            "candidate_id": "PRC-" + "0" * 64,
            "source": {
                "anchor_event_id": EVENT_A,
                "anchor_event_sequence": 4,
                "anchor_generation": 0,
                "anchor_sha256": SHA_A,
                "manifest_file_sha256": SHA_B,
                "basis_sha256": SHA_C,
                "policy_sha256": SHA_D,
                "coverage_group_sha256": SHA_E,
                "admission_sha256": SHA_F,
            },
            "observation": {
                "observed_through_event_sequence": 9,
                "observed_through_event_id": EVENT_B,
                "observed_through_anchor_event_id": EVENT_A,
            },
            "target": {"type": "task", "id": "T-0001"},
            "candidate": {
                "object_format": "sha1",
                "commit_oid": "1" * 40,
                "tree_oid": "2" * 40,
            },
            "current_proof": {
                "scope": "feature",
                "status": "healthy",
                "match_status": "matched",
                "proof_sha256": SHA_A,
            },
            "roles": [
                {
                    "role": "full_regression",
                    "kind": "full_regression",
                    "canary_id": None,
                    "requirement_sha256": SHA_A,
                    "participant_sha256": SHA_B,
                    "check_id": "full-regression",
                    "plan_sha256": SHA_C,
                    "tool_identity_sha256": SHA_D,
                    "public_execution_sha256": SHA_E,
                    "spawn_vector_sha256": SHA_F,
                    "external_input_binding_sha256": SHA_A,
                    "execution_binding_sha256": SHA_B,
                    "packet_sha256": SHA_C,
                    "final_authority_checkpoint_sha256": SHA_D,
                    "result_sha256": SHA_E,
                    "receipt_sha256": SHA_F,
                    "aggregate_sha256": SHA_A,
                    "bundle_sha256": SHA_B,
                    "verdict": "passed",
                    "output_commitment_status": "committed",
                    "effect_classification": "read_only",
                }
            ],
            "authorization": dict(REUSE_CANDIDATE_AUTHORIZATION),
            "handoff": dict(REUSE_CANDIDATE_HANDOFF),
            "effects": dict(REUSE_CANDIDATE_EFFECTS_SUCCESS),
            "candidate_sha256": SHA_A,
        }
    )


def _result(profile: str = "fresh") -> dict:
    candidate = _candidate()
    replay = profile == "replay"
    unhealthy = profile == "postcommit_unhealthy"
    return finalize_proof_reuse_candidate_result(
        {
            "contract_version": PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
            "ok": not unhealthy,
            "status": "recordable",
            "status_rank": 0,
            "changed": not replay,
            "idempotent": replay,
            "mutation_committed": not replay,
            "safe_to_retry_original": replay,
            "candidate_id": candidate["candidate_id"],
            "candidate": candidate,
            "reason_codes": [],
            "projection": {
                "status": "replayed" if replay else "committed",
                "evidence_id": "E-0001",
                "event_id": EVENT_B,
                "event_sequence": 10,
                "outbox_id": "OB-" + "C" * 64,
                "artifact_id": candidate["candidate_id"],
            },
            "outbox_delivery": "delivered",
            "health": {
                "source_anchor": "healthy",
                "candidate_artifact": (
                    "postcommit_unhealthy" if unhealthy else "healthy"
                ),
                "postcommit_checked": True,
            },
            "effects": dict(
                REUSE_CANDIDATE_EFFECTS_ZERO
                if replay
                else REUSE_CANDIDATE_EFFECTS_SUCCESS
            ),
            "result_sha256": SHA_A,
        }
    )


def _nonrecordable(reason: str) -> dict:
    status = REUSE_CANDIDATE_REASON_STATUS[reason]
    source_health = {
        "invalid": "invalid",
        "unavailable": "unavailable",
        "withheld": "recovery_required",
    }[status]
    return finalize_proof_reuse_candidate_result(
        {
            "contract_version": PROOF_REUSE_CANDIDATE_RESULT_CONTRACT_VERSION,
            "ok": False,
            "status": status,
            "status_rank": REUSE_CANDIDATE_STATUS_RANK[status],
            "changed": False,
            "idempotent": False,
            "mutation_committed": False,
            "safe_to_retry_original": True,
            "candidate_id": None,
            "candidate": None,
            "reason_codes": [reason],
            "projection": {
                "status": "none",
                "evidence_id": None,
                "event_id": None,
                "event_sequence": None,
                "outbox_id": None,
                "artifact_id": None,
            },
            "outbox_delivery": "not_applicable",
            "health": {
                "source_anchor": source_health,
                "candidate_artifact": "not_applicable",
                "postcommit_checked": False,
            },
            "effects": dict(REUSE_CANDIDATE_EFFECTS_ZERO),
            "result_sha256": SHA_A,
        }
    )


def test_exactly_two_closed_draft_2020_12_schemas_and_golden_digests() -> None:
    candidate_schema = proof_reuse_candidate_schema()
    result_schema = proof_reuse_candidate_result_schema()
    Draft202012Validator.check_schema(candidate_schema)
    Draft202012Validator.check_schema(result_schema)
    assert candidate_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert result_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def assert_closed(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" or "properties" in value:
                assert value.get("additionalProperties") is False
            for nested in value.values():
                assert_closed(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_closed(nested)

    assert_closed(candidate_schema)
    assert_closed(result_schema)
    candidate = _candidate()
    assert validate_proof_reuse_candidate(candidate).ok
    assert candidate["candidate_id"] == proof_reuse_candidate_id(candidate)
    assert candidate["candidate_sha256"] == proof_reuse_candidate_sha256(candidate)
    assert canonical_proof_reuse_candidate_bytes(candidate).endswith(b"}")
    assert not canonical_proof_reuse_candidate_bytes(candidate).endswith(b"\n")
    assert all(validate_proof_reuse_candidate_result(_result(profile)).ok for profile in (
        "fresh",
        "replay",
        "postcommit_unhealthy",
    ))


def test_hwm_is_excluded_from_identity_but_first_writer_body_remains_bound() -> None:
    first = _candidate()
    later = deepcopy(first)
    later["observation"]["observed_through_event_sequence"] += 10
    later["observation"]["observed_through_event_id"] = "EV-" + "D" * 64
    later = finalize_proof_reuse_candidate(later)
    assert later["candidate_id"] == first["candidate_id"]
    assert later["candidate_sha256"] != first["candidate_sha256"]

    proof = deepcopy(first)
    proof["current_proof"]["proof_sha256"] = SHA_F
    proof = finalize_proof_reuse_candidate(proof)
    assert proof["candidate_id"] != first["candidate_id"]

    role = deepcopy(first)
    role["roles"][0]["participant_sha256"] = SHA_F
    role = finalize_proof_reuse_candidate(role)
    assert role["candidate_id"] != first["candidate_id"]


def test_all_reasons_are_closed_sorted_and_map_to_exact_status_rank() -> None:
    assert len(REUSE_CANDIDATE_REASON_CODES) == 18
    assert REUSE_CANDIDATE_REASON_CODES == tuple(sorted(REUSE_CANDIDATE_REASON_CODES))
    assert len(REUSE_CANDIDATE_HARD_ERROR_CODES) == 13
    assert REUSE_CANDIDATE_ERROR_PHASES == (
        "preflight",
        "lock",
        "authority",
        "live",
        "identity",
        "replay",
        "publication",
        "transaction",
        "final_guard",
        "projection",
        "postcommit",
        "cleanup",
    )
    for reason in REUSE_CANDIDATE_REASON_CODES:
        result = _nonrecordable(reason)
        assert validate_proof_reuse_candidate_result(result).ok
        assert result["status"] == REUSE_CANDIDATE_REASON_STATUS[reason]
        assert result["status_rank"] == REUSE_CANDIDATE_STATUS_RANK[result["status"]]
    assert status_for_reasons(
        ["source_anchor_recovery_required", "source_anchor_not_found"]
    ) == "unavailable"
    assert status_for_reasons(
        ["source_anchor_not_found", "source_authorization_invalid"]
    ) == "invalid"


def test_rights_effects_currentness_privacy_unknowns_and_caps_fail_closed() -> None:
    candidate = _candidate()
    mutants: list[dict] = []

    right = deepcopy(candidate)
    right["authorization"]["reuse_authorized"] = True
    mutants.append(right)

    handoff = deepcopy(candidate)
    handoff["handoff"]["consumer_enabled"] = True
    mutants.append(handoff)

    effect = deepcopy(candidate)
    effect["effects"]["events_appended"] = 2
    mutants.append(effect)

    current = deepcopy(candidate)
    current["current_proof"]["match_status"] = "mismatched"
    mutants.append(current)

    unknown = deepcopy(candidate)
    unknown["future_right"] = True
    mutants.append(unknown)

    secret = deepcopy(candidate)
    secret["target"]["id"] = "token=0123456789abcdef0123456789abcdef"
    mutants.append(secret)

    public_cap = deepcopy(candidate)
    public_cap["target"]["id"] = "T" * 4097
    mutants.append(public_cap)

    role_cap = deepcopy(candidate)
    role_cap["roles"] = role_cap["roles"] * 4097
    mutants.append(role_cap)

    nan_value = deepcopy(candidate)
    nan_value["observation"]["observed_through_event_sequence"] = float("nan")
    mutants.append(nan_value)

    for mutant in mutants:
        assert not validate_proof_reuse_candidate(mutant).ok

    replay = _result("replay")
    rebuilt = deepcopy(replay)
    rebuilt["candidate"]["observation"]["observed_through_event_sequence"] += 1
    rebuilt = finalize_proof_reuse_candidate_result(rebuilt)
    assert not validate_proof_reuse_candidate_result(rebuilt).ok
