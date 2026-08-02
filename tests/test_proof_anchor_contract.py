from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from pcl.approval_provenance import ACTOR_KINDS, SOURCE_KINDS
from pcl.contracts.proof_anchor import (
    ANCHOR_EFFECTS_SUCCESS,
    PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION,
    PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION,
    PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION,
    PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION,
    anchor_sha256,
    authorization_sha256,
    authorization_subject_sha256,
    base_request_sha256,
    canonical_proof_anchor_bytes,
    exhaustion_event_id,
    exhaustion_outbox_id,
    finalize_proof_admission_anchor,
    finalize_proof_admission_anchor_basis,
    finalize_proof_admission_authorization,
    finalize_proof_anchor_health,
    manifest_file_sha256,
    proof_admission_anchor_basis_schema,
    proof_admission_anchor_result_schema,
    proof_admission_anchor_schema,
    proof_admission_authorization_schema,
    proof_anchor_event_id,
    proof_anchor_outbox_id,
    proof_anchor_request_id,
    validate_proof_admission_anchor,
    validate_proof_admission_anchor_basis,
    validate_proof_admission_anchor_result,
    validate_proof_admission_authorization,
    validate_proof_anchor_event,
    validate_proof_anchor_exhaustion_event,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
SHA_E = "sha256:" + "e" * 64
OID = "1" * 40


def _h(domain: str, value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(b"pcl:" + domain.encode() + b"\0" + encoded).hexdigest()


def _policy() -> dict:
    return {
        "contract_version": "proof-coverage-policy/v1",
        "policy_id": "policy-1",
        "producer": {
            "kind": "external_bootstrap",
            "producer_id": "agent:policy-producer",
            "producer_sha256": SHA_A,
            "candidate_controlled": False,
        },
        "target": {"type": "task", "id": "T-0001"},
        "candidate": {
            "object_format": "sha1",
            "commit_oid": OID,
            "tree_oid": "2" * 40,
        },
        "authority_bindings": {
            "authority_surface_resolution_sha256": SHA_A,
            "bootstrap_profile_sha256": SHA_B,
            "canary_union_sha256": SHA_C,
            "isolation_contract_version": "proof-workspace-isolation/v1",
        },
        "coverage_group_sha256": SHA_D,
        "required_roles": [],
        "authorization_requirements": {
            "independent_review": "required",
            "human_gate": "required",
            "self_certification_allowed": False,
        },
        "terminal_authority": False,
        "mandatory_evidence": False,
        "policy_sha256": SHA_E,
    }


def _admission() -> dict:
    return {
        "contract_version": "proof-coverage-admission/v1",
        "policy_sha256": SHA_E,
        "coverage_group_sha256": SHA_D,
        "participants": [],
        "role_observations": [],
        "current_proof": {
            "scope": "not_applicable",
            "status": "not_applicable",
            "proof_sha256": SHA_A,
            "match_status": "matched",
        },
        "admission_state": "reviewable",
        "state_reason_codes": [],
        "review_readiness": "ready",
        "promotion_suitability": "candidate",
        "promotion_withholding_codes": [],
        "authorization_status": {
            "independent_review": "pending",
            "human_gate": "pending",
            "anchoring_authorized": False,
            "reuse_authorized": False,
            "terminal_authority": False,
            "mandatory_evidence": False,
        },
        "effects": {
            "schema": 0,
            "migration": 0,
            "database_write": 0,
            "filesystem_write": 0,
            "evidence": 0,
            "event": 0,
            "outbox": 0,
            "render": 0,
            "lifecycle": 0,
        },
        "admission_sha256": SHA_B,
    }


def _basis() -> dict:
    return finalize_proof_admission_anchor_basis(
        {
            "contract_version": PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION,
            "target": {"type": "task", "id": "T-0001"},
            "candidate": {
                "object_format": "sha1",
                "commit_oid": OID,
                "tree_oid": "2" * 40,
            },
            "policy": _policy(),
            "admission": _admission(),
            "bindings": {
                "policy_sha256": SHA_E,
                "coverage_group_sha256": SHA_D,
                "admission_sha256": SHA_B,
            },
            "scope": {
                "anchor": True,
                "reuse": False,
                "terminal": False,
                "publication": False,
            },
            "basis_sha256": SHA_A,
        }
    )


def _authorization(kind: str = "independent_review") -> dict:
    basis = _basis()
    human = kind == "human_gate"
    value = {
        "contract_version": PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION,
        "authorization_id": "PAUTH-human" if human else "PAUTH-review",
        "authorization_kind": kind,
        "decision": "approved",
        "authority": {
            "actor_kind": "human" if human else "agent",
            "actor_id": "human:owner" if human else "agent:reviewer",
            "recorder_kind": "human" if human else "agent",
            "recorder_id": "human:owner" if human else "agent:reviewer",
            "source_kind": "cli",
            "source_ref": "",
            "candidate_controlled": False,
        },
        "target": deepcopy(basis["target"]),
        "candidate": deepcopy(basis["candidate"]),
        "bindings": {
            "basis_sha256": basis["basis_sha256"],
            "policy_sha256": SHA_E,
            "coverage_group_sha256": SHA_D,
            "admission_sha256": SHA_B,
            "producer_sha256": SHA_A,
        },
        "authorization_subject_sha256": SHA_A,
        "review": (
            None
            if human
            else {
                "report_sha256": SHA_C,
                "report_size_bytes": 123,
                "findings": {"high": 0, "medium": 0, "low": 1},
            }
        ),
        "scope": {
            "anchor": True,
            "reuse": False,
            "terminal": False,
            "publication": False,
        },
        "issued_at": "2026-08-02T00:00:00Z",
        "reason": "Exact anchor-only approval.",
        "authorization_sha256": SHA_A,
    }
    return finalize_proof_admission_authorization(value)


def _anchor(*, human_gate: bool) -> dict:
    basis = _basis()
    review = _authorization()
    human = _authorization("human_gate") if human_gate else None
    members = [
        {
            "role": "basis",
            "storage_name": "basis.json",
            "size_bytes": 100,
            "file_sha256": SHA_A,
        },
        {
            "role": "independent_review",
            "storage_name": "independent-review.json",
            "size_bytes": 101,
            "file_sha256": SHA_B,
        },
    ]
    if human is not None:
        members.append(
            {
                "role": "human_gate",
                "storage_name": "human-gate.json",
                "size_bytes": 102,
                "file_sha256": SHA_C,
            }
        )
    base = base_request_sha256(
        project_instance_id="f" * 64,
        target=basis["target"],
        candidate=basis["candidate"],
        basis_sha256_value=basis["basis_sha256"],
        independent_review_subject_sha256=review["authorization_subject_sha256"],
        human_gate_subject_sha256=(
            None if human is None else human["authorization_subject_sha256"]
        ),
    )
    request_id = proof_anchor_request_id(
        base_request_sha256_value=base,
        anchor_generation=0,
        recovery_predecessor=None,
    )
    value = {
        "contract_version": PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION,
        "request": {
            "request_id": request_id,
            "base_request_sha256": base,
            "anchor_generation": 0,
            "recovery": None,
        },
        "epoch": {
            "contract_version": "proof-admission-anchor-epoch/v1",
            "request_id": request_id,
            "base_request_sha256": base,
            "anchor_generation": 0,
            "precommit_hwm": {"sequence": 7, "event_id": "EV-" + "A" * 64},
            "ledger_predecessor": {"event_id": None, "anchor_sha256": None},
            "recovery_predecessor": None,
            "epoch_sha256": SHA_D,
        },
        "target": deepcopy(basis["target"]),
        "candidate": deepcopy(basis["candidate"]),
        "bindings": {
            "basis_sha256": basis["basis_sha256"],
            "policy_sha256": SHA_E,
            "coverage_group_sha256": SHA_D,
            "admission_sha256": SHA_B,
            "independent_review_authorization_sha256": review["authorization_sha256"],
            "independent_review_subject_sha256": review["authorization_subject_sha256"],
            "human_gate_authorization_sha256": (
                None if human is None else human["authorization_sha256"]
            ),
            "human_gate_subject_sha256": (
                None if human is None else human["authorization_subject_sha256"]
            ),
        },
        "members": members,
        "authorization_projection": {
            "independent_review": "approved",
            "human_gate": "approved" if human_gate else "not_required",
            "authorized_actions": ["anchor"],
            "anchor_authorization_granted": True,
            "reuse_authorized": False,
            "terminal_authority": False,
            "mandatory_evidence": False,
            "publication_authorized": False,
        },
        "handoff": {
            "status": "anchored_candidate",
            "reuse_consumable": False,
            "terminal_consumable": False,
            "promotion_authorized": False,
        },
        "effects": deepcopy(ANCHOR_EFFECTS_SUCCESS),
        "anchor_sha256": SHA_A,
    }
    return finalize_proof_admission_anchor(value)


def test_four_draft_2020_12_schemas_are_strict_and_parseable() -> None:
    schemas = (
        proof_admission_anchor_basis_schema(),
        proof_admission_authorization_schema(),
        proof_admission_anchor_schema(),
        proof_admission_anchor_result_schema(),
    )
    assert [schema["$schema"] for schema in schemas] == [
        "https://json-schema.org/draft/2020-12/schema"
    ] * 4
    assert [schema["additionalProperties"] for schema in schemas] == [False] * 4
    assert [schema["$id"] for schema in schemas] == [
        "proof-admission-anchor-basis/v1",
        "proof-admission-authorization/v1",
        "proof-admission-anchor/v1",
        "proof-admission-anchor-result/v1",
    ]
    schema_dir = Path(__file__).parents[1] / "src/pcl/contracts/schemas"
    for name in (
        "proof-admission-anchor-basis-v1.schema.json",
        "proof-admission-authorization-v1.schema.json",
        "proof-admission-anchor-v1.schema.json",
        "proof-admission-anchor-result-v1.schema.json",
    ):
        parsed = json.loads((schema_dir / name).read_text(encoding="utf-8"))
        assert parsed["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert parsed["additionalProperties"] is False


def test_digest_domains_and_known_bytes_are_independent_goldens() -> None:
    basis = _basis()
    expected_basis = _h(
        "proof-admission-anchor-basis/v1",
        {key: value for key, value in basis.items() if key != "basis_sha256"},
    )
    assert basis["basis_sha256"] == expected_basis
    assert basis["basis_sha256"] == "sha256:5ba23c6332ddaf8f5071288ba503f601e9af18feb51a6f1aecc072f48172f740"

    review = _authorization()
    assert review["authorization_subject_sha256"] == authorization_subject_sha256(review)
    assert review["authorization_sha256"] == authorization_sha256(review)
    mutated = deepcopy(review)
    mutated["issued_at"] = "2026-08-03T00:00:00Z"
    mutated = finalize_proof_admission_authorization(mutated)
    assert mutated["authorization_subject_sha256"] == review["authorization_subject_sha256"]
    assert mutated["authorization_sha256"] != review["authorization_sha256"]


@pytest.mark.parametrize("human_gate", [False, True])
def test_anchor_manifest_is_non_self_referential_and_fixed_order(human_gate: bool) -> None:
    anchor = _anchor(human_gate=human_gate)
    assert validate_proof_admission_anchor(anchor).ok
    assert [member["role"] for member in anchor["members"]] == (
        ["basis", "independent_review", "human_gate"]
        if human_gate
        else ["basis", "independent_review"]
    )
    assert "evidence-manifest.json" not in {
        member["storage_name"] for member in anchor["members"]
    }
    serialized = json.dumps(anchor, sort_keys=True)
    assert "evidence_id" not in serialized
    assert "outbox_id" not in serialized
    assert set(anchor) == {
        "contract_version",
        "request",
        "epoch",
        "target",
        "candidate",
        "bindings",
        "members",
        "authorization_projection",
        "handoff",
        "effects",
        "anchor_sha256",
    }
    assert anchor["anchor_sha256"] == anchor_sha256(anchor)
    manifest_bytes = canonical_proof_anchor_bytes(anchor) + b"\n"
    assert manifest_file_sha256(manifest_bytes) == (
        "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    )


def test_recovery_manifest_embeds_complete_health_and_request_binds_summary() -> None:
    predecessor = _anchor(human_gate=False)
    predecessor_event_id = proof_anchor_event_id(predecessor["request"]["request_id"])
    health = finalize_proof_anchor_health(
        {
            "contract_version": "proof-admission-anchor-health/v1",
            "predecessor": {
                "request_id": predecessor["request"]["request_id"],
                "anchor_generation": 0,
                "event_id": predecessor_event_id,
                "anchor_sha256": predecessor["anchor_sha256"],
                "manifest_file_sha256": SHA_C,
            },
            "authority_components": {
                "evidence_row": "matched",
                "evidence_link": "matched",
                "event": "matched",
                "outbox": "matched",
            },
            "artifact_observations": [
                {
                    "role": "manifest",
                    "storage_name": "evidence-manifest.json",
                    "status": "hash_mismatch",
                    "expected_size_bytes": 100,
                    "observed_size_bytes": 100,
                    "expected_file_sha256": SHA_C,
                    "observed_file_sha256": SHA_D,
                }
            ],
            "finding_codes": ["proof_anchor_manifest_hash_mismatch"],
            "health_sha256": SHA_A,
        }
    )
    recovery_predecessor = {
        "request_id": health["predecessor"]["request_id"],
        "anchor_generation": health["predecessor"]["anchor_generation"],
        "event_id": health["predecessor"]["event_id"],
        "anchor_sha256": health["predecessor"]["anchor_sha256"],
        "health_sha256": health["health_sha256"],
    }
    recovery = deepcopy(predecessor)
    recovery["request"]["anchor_generation"] = 1
    recovery["request"]["recovery"] = health
    recovery["request"]["request_id"] = proof_anchor_request_id(
        base_request_sha256_value=recovery["request"]["base_request_sha256"],
        anchor_generation=1,
        recovery_predecessor=recovery_predecessor,
    )
    recovery["epoch"].update(
        {
            "request_id": recovery["request"]["request_id"],
            "anchor_generation": 1,
            "ledger_predecessor": {
                "event_id": predecessor_event_id,
                "anchor_sha256": predecessor["anchor_sha256"],
            },
            "recovery_predecessor": recovery_predecessor,
        }
    )
    recovery = finalize_proof_admission_anchor(recovery)
    assert validate_proof_admission_anchor(recovery).ok
    assert recovery["request"]["recovery"] == health
    assert recovery["epoch"]["recovery_predecessor"] == recovery_predecessor

    tampered = deepcopy(recovery)
    tampered["request"]["recovery"]["artifact_observations"][0][
        "observed_file_sha256"
    ] = SHA_E
    tampered = finalize_proof_admission_anchor(tampered)
    assert not validate_proof_admission_anchor(tampered).ok


def test_authorization_namespaces_independence_and_helper_enum_parity() -> None:
    review = _authorization()
    assert validate_proof_admission_authorization(review).ok
    assert review["authority"]["actor_kind"] in ACTOR_KINDS
    assert review["authority"]["source_kind"] in SOURCE_KINDS
    for path, value in (
        (("authority", "candidate_controlled"), True),
        (("scope", "reuse"), True),
        (("review", "findings", "high"), 1),
        (("reason",), "x" * 16_385),
    ):
        mutated = deepcopy(review)
        cursor = mutated
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = value
        mutated = finalize_proof_admission_authorization(mutated)
        assert not validate_proof_admission_authorization(mutated).ok

    basis = _basis()
    assert validate_proof_admission_anchor_basis(basis).ok
    embedded = basis["admission"]["authorization_status"]
    assert embedded == {
        "independent_review": "pending",
        "human_gate": "pending",
        "anchoring_authorized": False,
        "reuse_authorized": False,
        "terminal_authority": False,
        "mandatory_evidence": False,
    }
    assert _anchor(human_gate=True)["authorization_projection"] == {
        "independent_review": "approved",
        "human_gate": "approved",
        "authorized_actions": ["anchor"],
        "anchor_authorization_granted": True,
        "reuse_authorized": False,
        "terminal_authority": False,
        "mandatory_evidence": False,
        "publication_authorized": False,
    }


def test_event_and_exhaustion_id_domains_and_private_field_rejection() -> None:
    request_id = "PA-" + "A" * 64
    assert proof_anchor_event_id(request_id).startswith("EV-")
    assert proof_anchor_outbox_id(request_id).startswith("OB-")
    assert len(proof_anchor_event_id(request_id)) == 67
    assert len(proof_anchor_outbox_id(request_id)) == 67
    assert exhaustion_event_id(
        project_instance_id="f" * 64,
        target={"type": "task", "id": "T-0001"},
        basis_sha256_value=SHA_A,
    ) != exhaustion_outbox_id(
        project_instance_id="f" * 64,
        target={"type": "task", "id": "T-0001"},
        basis_sha256_value=SHA_A,
    ).replace("OB-", "EV-", 1)

    payload = {
        "contract_version": PROOF_ADMISSION_ANCHOR_EVENT_CONTRACT_VERSION,
        "request_id": request_id,
        "base_request_sha256": SHA_A,
        "anchor_generation": 0,
        "basis_sha256": SHA_B,
        "anchor_sha256": SHA_C,
        "manifest_file_sha256": SHA_D,
        "evidence_id": "E-0001",
    }
    assert validate_proof_anchor_event(payload).ok
    for forbidden in ("actor_id", "source_ref", "reason", "report_bytes"):
        mutated = {**payload, forbidden: "secret"}
        assert not validate_proof_anchor_event(mutated).ok

    exhausted = {
        "contract_version": PROOF_ADMISSION_EXHAUSTION_EVENT_CONTRACT_VERSION,
        "base_request_sha256": SHA_A,
        "anchor_generation": 3,
        "basis_sha256": SHA_B,
        "anchor_sha256": SHA_C,
        "manifest_file_sha256": SHA_D,
        "exhausted_request_id": request_id,
        "exhausted_anchor_event_id": "EV-" + "B" * 64,
        "health_sha256": SHA_E,
        "disposition": "human_design_required",
    }
    assert validate_proof_anchor_exhaustion_event(exhausted).ok
    assert exhausted["contract_version"] == (
        "proof-admission-anchor-recovery-exhausted-event/v1"
    )


def test_result_envelope_accepts_only_exact_effect_matrices() -> None:
    result = {
        "contract_version": PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION,
        "ok": True,
        "status": "anchored",
        "changed": True,
        "idempotent": False,
        "mutation_committed": True,
        "safe_to_retry_original": False,
        "request_id": "PA-" + "A" * 64,
        "base_request_sha256": SHA_A,
        "anchor_generation": 0,
        "basis_sha256": SHA_B,
        "anchor_sha256": SHA_C,
        "manifest_file_sha256": SHA_D,
        "evidence_id": "E-0001",
        "event_id": "EV-" + "A" * 64,
        "outbox_id": "OB-" + "A" * 64,
        "projection": "delivered",
        "health": "healthy",
        "effects": deepcopy(ANCHOR_EFFECTS_SUCCESS),
        "recovery_action": None,
    }
    assert validate_proof_admission_anchor_result(result).ok
    tampered = deepcopy(result)
    tampered["effects"]["lifecycle_transitions"] = 1
    assert not validate_proof_admission_anchor_result(tampered).ok
    assert not validate_proof_admission_anchor_result(
        {**result, "actor_id": "agent:private"}
    ).ok


def test_nan_cap_and_every_nonself_basis_mutation_fail_closed() -> None:
    basis = _basis()
    for field in (
        "contract_version",
        "target",
        "candidate",
        "policy",
        "admission",
        "bindings",
        "scope",
    ):
        mutated = deepcopy(basis)
        if isinstance(mutated[field], dict):
            mutated[field]["unexpected"] = "x"
        else:
            mutated[field] = "x"
        assert not validate_proof_admission_anchor_basis(mutated).ok
    with pytest.raises(ValueError):
        canonical_proof_anchor_bytes({"value": float("nan")})


def test_result_contract_versions_are_distinct() -> None:
    assert len(
        {
            PROOF_ADMISSION_ANCHOR_BASIS_CONTRACT_VERSION,
            PROOF_ADMISSION_AUTHORIZATION_CONTRACT_VERSION,
            PROOF_ADMISSION_ANCHOR_CONTRACT_VERSION,
            PROOF_ADMISSION_ANCHOR_RESULT_CONTRACT_VERSION,
        }
    ) == 4
