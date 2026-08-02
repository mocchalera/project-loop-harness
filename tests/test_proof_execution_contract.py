from __future__ import annotations

from copy import deepcopy

import pytest

from pcl.contracts.proof_execution import (
    PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION,
    PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION,
    PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION,
    PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION,
    PROOF_EXECUTION_PACKET_CONTRACT_VERSION,
    PROOF_EXECUTION_RESULT_CONTRACT_VERSION,
    PROOF_STREAM_LOG_CONTRACT_VERSION,
    finalize_proof_execution_document,
    proof_authority_checkpoint_schema,
    proof_check_execution_receipt_schema,
    proof_check_execution_result_schema,
    proof_execution_bundle_receipt_schema,
    proof_execution_packet_schema,
    proof_execution_result_schema,
    proof_stream_log_schema,
    validate_proof_execution_document,
)


SHA = "sha256:" + "a" * 64


def _finalize(value: dict) -> dict:
    return finalize_proof_execution_document(value)


def _documents() -> list[dict]:
    packet = _finalize(
        {
            "contract_version": PROOF_EXECUTION_PACKET_CONTRACT_VERSION,
            "workspace_binding_sha256": SHA,
            "executor_contract_sha256": SHA,
            "ordered_check_ids": ["full-regression"],
            "initial_reuse_disposition": "eligible",
        }
    )
    checkpoint = _finalize(
        {
            "contract_version": PROOF_AUTHORITY_CHECKPOINT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "phase": "initial",
            "check_id": None,
            "source_status": "matched",
            "base_status": "resolved",
            "literal_reuse_allowed": True,
            "rederived_cross_checks": {
                "binding": True,
                "bootstrap_profile": True,
                "verification_profile": True,
                "check_plan": True,
                "external_inputs": True,
                "proof_key": True,
                "public_execution": True,
            },
            "clone_diff_cross_check": {
                "status": "matched",
                "diff_sha256": SHA,
            },
        }
    )
    stdout = _finalize(
        {
            "contract_version": PROOF_STREAM_LOG_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "check_id": "full-regression",
            "stream": "stdout",
            "commitment": "committed",
            "content_byte_count": 0,
            "content_base64": "",
            "content_sha256": "sha256:" + "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
        }
    )
    stderr = deepcopy(stdout)
    stderr["stream"] = "stderr"
    stderr.pop("log_sha256")
    stderr = _finalize(stderr)
    receipt = _finalize(
        {
            "contract_version": PROOF_CHECK_EXECUTION_RECEIPT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "check_id": "full-regression",
            "authority_checkpoint_sha256s": [checkpoint["checkpoint_sha256"]],
            "spawn": {"status": "spawned", "error_kind": None},
            "process": {
                "controller_cause": "exit",
                "leader_kind": "exited",
                "leader_value": 0,
                "term_sent": False,
                "kill_sent": False,
                "pipes_eof": True,
                "group_quiescent": True,
            },
            "stdout_log_sha256": stdout["log_sha256"],
            "stderr_log_sha256": stderr["log_sha256"],
            "reseal": {
                "status": "matched",
                "before_manifest_sha256": SHA,
                "after_manifest_sha256": SHA,
                "effect_classification": "read_only",
            },
            "proof_validity": "valid",
        }
    )
    result = _finalize(
        {
            "contract_version": PROOF_CHECK_EXECUTION_RESULT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "check_id": "full-regression",
            "receipt_sha256": receipt["receipt_sha256"],
            "verdict": "passed",
            "reuse_disposition": "eligible",
        }
    )
    aggregate = _finalize(
        {
            "contract_version": PROOF_EXECUTION_RESULT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "ordered_result_sha256s": [result["result_sha256"]],
            "not_run_check_ids": [],
            "final_authority_checkpoint_sha256": checkpoint["checkpoint_sha256"],
            "verdict": "passed",
            "output_commitment_status": "committed",
            "current_proof": {
                "scope": "feature",
                "status": "healthy",
                "proof_sha256": SHA,
            },
            "anchoring_eligible": True,
            "positive_proof_handoff": "candidate",
            "reuse_disposition": "eligible",
            "reuse_authorized": False,
        }
    )
    bundle = _finalize(
        {
            "contract_version": PROOF_EXECUTION_BUNDLE_RECEIPT_CONTRACT_VERSION,
            "packet_sha256": packet["packet_sha256"],
            "aggregate_sha256": aggregate["aggregate_sha256"],
            "objects": [
                {
                    "role": "aggregate",
                    "sha256": aggregate["aggregate_sha256"],
                },
                {"role": "packet", "sha256": packet["packet_sha256"]},
            ],
        }
    )
    return [packet, checkpoint, stdout, receipt, result, aggregate, bundle]


def test_all_seven_contracts_are_strict_canonical_and_packaged() -> None:
    schemas = [
        proof_execution_packet_schema(),
        proof_authority_checkpoint_schema(),
        proof_stream_log_schema(),
        proof_check_execution_receipt_schema(),
        proof_check_execution_result_schema(),
        proof_execution_result_schema(),
        proof_execution_bundle_receipt_schema(),
    ]
    assert len(schemas) == 7
    assert all(schema["$schema"] == "https://json-schema.org/draft/2020-12/schema" for schema in schemas)
    assert all(schema["additionalProperties"] is False for schema in schemas)

    for document in _documents():
        validation = validate_proof_execution_document(document)
        assert validation.ok, validation.errors
        assert _finalize(document) == document

        extra = deepcopy(document)
        extra["unexpected"] = True
        assert not validate_proof_execution_document(extra).ok


def test_current_proof_digest_is_strictly_nullable_only_for_indeterminate() -> None:
    aggregate = _documents()[-2]
    aggregate["current_proof"] = {
        "scope": "feature",
        "status": "indeterminate",
        "proof_sha256": None,
    }
    aggregate["anchoring_eligible"] = False
    aggregate["positive_proof_handoff"] = "withheld"
    aggregate["reuse_disposition"] = "fresh_only"
    aggregate.pop("aggregate_sha256")
    aggregate = _finalize(aggregate)
    assert validate_proof_execution_document(aggregate).ok

    non_null = deepcopy(aggregate)
    non_null["current_proof"]["proof_sha256"] = SHA
    non_null.pop("aggregate_sha256")
    non_null = _finalize(non_null)
    assert not validate_proof_execution_document(non_null).ok

    healthy_null = deepcopy(aggregate)
    healthy_null["current_proof"] = {
        "scope": "feature",
        "status": "healthy",
        "proof_sha256": None,
    }
    healthy_null.pop("aggregate_sha256")
    healthy_null = _finalize(healthy_null)
    assert not validate_proof_execution_document(healthy_null).ok


def test_anchoring_suitability_requires_final_authority_and_is_biconditional() -> None:
    aggregate = _documents()[-2]
    aggregate["final_authority_checkpoint_sha256"] = None
    aggregate.pop("aggregate_sha256")
    aggregate = _finalize(aggregate)
    assert not validate_proof_execution_document(aggregate).ok

    aggregate["anchoring_eligible"] = False
    aggregate["positive_proof_handoff"] = "withheld"
    aggregate["reuse_disposition"] = "fresh_only"
    aggregate.pop("aggregate_sha256")
    aggregate = _finalize(aggregate)
    assert validate_proof_execution_document(aggregate).ok


@pytest.mark.parametrize(
    ("status", "diff"),
    [
        ("matched", None),
        ("not_applicable_base_unknown", SHA),
    ],
)
def test_clone_diff_cross_check_rejects_invalid_cross_field_pairs(
    status: str,
    diff: str | None,
) -> None:
    checkpoint = _documents()[1]
    checkpoint["clone_diff_cross_check"] = {"status": status, "diff_sha256": diff}
    checkpoint.pop("checkpoint_sha256")
    checkpoint = _finalize(checkpoint)
    assert not validate_proof_execution_document(checkpoint).ok


def test_uncommitted_stream_has_no_bytes_count_or_digest() -> None:
    stream = _documents()[2]
    for field in ("content_byte_count", "content_base64", "content_sha256"):
        stream.pop(field)
    stream["commitment"] = "uncommitted"
    stream["reason_codes"] = ["secret_shape_match"]
    stream.pop("log_sha256")
    stream = _finalize(stream)
    assert validate_proof_execution_document(stream).ok

    stream["content_byte_count"] = 0
    stream.pop("log_sha256")
    stream = _finalize(stream)
    assert not validate_proof_execution_document(stream).ok
