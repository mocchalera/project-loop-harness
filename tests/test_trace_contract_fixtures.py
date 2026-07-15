from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from pcl.contracts.handoff_packet import handoff_packet_schema
from pcl.contracts.intent_index import select_trace_claim_refs, validate_intent_index_binding


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "trace_binding_v0"
BINDING_FIXTURES = json.loads(
    (FIXTURE_ROOT / "trace-binding-fixtures.json").read_text(encoding="utf-8")
)
EVALUATION_FIXTURE = json.loads(
    (FIXTURE_ROOT / "trace-resume-evaluation-fixture.json").read_text(encoding="utf-8")
)


def _replace_path(value: dict[str, Any], path: str, replacement: Any) -> None:
    parts = path.split(".")
    current: Any = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    final = parts[-1]
    if isinstance(current, list):
        current[int(final)] = replacement
    else:
        current[final] = replacement


def _apply_mutations(index: dict[str, Any], mutations: list[dict[str, Any]]) -> None:
    for mutation in mutations:
        assert mutation["op"] == "replace"
        _replace_path(index, mutation["path"], mutation["value"])


def _binding_result(index: dict[str, Any]) -> dict[str, Any]:
    manifest = BINDING_FIXTURES["evidence_manifest"]
    trace_bytes = (FIXTURE_ROOT / BINDING_FIXTURES["trace_fixture_path"]).read_bytes()
    return validate_intent_index_binding(
        index,
        trace_evidence_id=manifest["evidence_id"],
        trace_manifest_path=manifest["manifest_path"],
        trace_member_path=manifest["member_path"],
        trace_stored_path=manifest["stored_path"],
        recorded_trace_sha256=manifest["sha256"],
        trace_bytes=trace_bytes,
    )


def test_trace_binding_fixture_bytes_and_baseline_are_consistent() -> None:
    assert BINDING_FIXTURES["contract_version"] == "trace-binding-fixtures/v0"
    trace_path = FIXTURE_ROOT / BINDING_FIXTURES["trace_fixture_path"]
    trace_bytes = trace_path.read_bytes()
    trace_text = trace_bytes.decode("utf-8")
    trace = BINDING_FIXTURES["trace"]
    manifest = BINDING_FIXTURES["evidence_manifest"]

    assert hashlib.sha256(trace_bytes).hexdigest() == trace["sha256"] == manifest["sha256"]
    assert len(trace_text.splitlines()) == trace["line_count"]
    assert f"contract_version: {trace['contract_version']}" in trace_text
    assert f"trace_id: {trace['trace_id']}" in trace_text

    index = BINDING_FIXTURES["intent_index"]
    assert _binding_result(index)["diagnostics"] == []


def test_trace_binding_cases_freeze_required_failure_classes() -> None:
    cases = BINDING_FIXTURES["cases"]
    assert [case["id"] for case in cases] == [
        "valid_binding",
        "hash_mismatch",
        "evidence_id_mismatch",
        "manifest_path_mismatch",
        "stored_path_mismatch",
        "unsupported_contract",
        "duplicate_item_id",
        "empty_source_refs",
        "reversed_line_range",
        "out_of_bounds_line_range",
    ]
    for case in cases:
        index = deepcopy(BINDING_FIXTURES["intent_index"])
        _apply_mutations(index, case["mutations"])
        result = _binding_result(index)
        errors = [item["code"] for item in result["diagnostics"]]
        assert errors == case["expected"]["error_codes"], case["id"]
        assert result["status"] == case["expected"]["status"]


def test_proposed_claim_refs_are_optional_bounded_and_unverified() -> None:
    extension = BINDING_FIXTURES["proposed_handoff_extension"]
    assert extension["field_name"] == "trace_claim_refs"
    assert extension["optional"] is True
    assert extension["trust_model"] == "claims-not-facts"
    assert extension["ordering"] == ["intent_index_ref", "item_id"]
    assert extension["omission_reasons"] == [
        "no_intent_index",
        "binding_invalid",
        "no_actionable_items",
        "packet_budget",
    ]
    assert "trace_claim_refs" in handoff_packet_schema()["properties"]

    examples = extension["example"]
    assert examples == sorted(examples, key=lambda item: (item["intent_index_ref"], item["item_id"]))
    for claim_ref in examples:
        assert claim_ref["trust"] == "unverified"
        assert claim_ref["source_refs"]
        assert not ({"source_text", "trace_text", "verified"} & claim_ref.keys())
        for source_ref in claim_ref["source_refs"]:
            assert set(source_ref) == {"evidence_id", "stored_path", "line_start", "line_end"}


def test_claim_ref_selection_is_deterministic_and_never_emits_partial_items() -> None:
    index = BINDING_FIXTURES["intent_index"]
    one_item = select_trace_claim_refs(
        index,
        intent_index_ref="evidence:E-9002",
        max_items=1,
        max_bytes=4096,
    )
    assert [item["item_id"] for item in one_item["trace_claim_refs"]] == ["I-001"]
    assert one_item["trace_claim_ref_omissions"] == [
        {"item_id": "I-002", "reason": "packet_budget"}
    ]
    assert one_item["trace_claim_ref_budget"]["included_items"] == 1

    no_bytes = select_trace_claim_refs(
        index,
        intent_index_ref="evidence:E-9002",
        max_items=8,
        max_bytes=1,
    )
    assert no_bytes["trace_claim_refs"] == []
    assert [item["item_id"] for item in no_bytes["trace_claim_ref_omissions"]] == [
        "I-001",
        "I-002",
    ]
    assert no_bytes["trace_claim_ref_budget"]["included_bytes"] == 0


def test_trace_resume_evaluation_fixture_freezes_cohort_and_result_contract() -> None:
    fixture = EVALUATION_FIXTURE
    assert fixture["contract_version"] == "trace-resume-evaluation-fixture/v0"
    cohort = fixture["minimum_cohort"]
    thresholds = fixture["promotion_thresholds"]
    cases = fixture["cases"]
    required_case_fields = set(fixture["required_case_fields"])

    assert len(cases) == cohort["case_count"] == 10
    assert len({case["repository_slot"] for case in cases}) >= cohort["owned_repository_count"]
    assert len({case["resume_session_id"] for case in cases}) >= cohort["resume_session_count"]
    cross_runtime_or_model = sum(
        case["source_runtime"] != case["resume_runtime"]
        or case["source_model"] != case["resume_model"]
        for case in cases
    )
    assert cross_runtime_or_model >= cohort["cross_runtime_or_model_count"]
    assert [case["id"] for case in cases] == [f"TRE-{number:03d}" for number in range(1, 11)]
    for case in cases:
        assert set(case) == required_case_fields
        assert case["binding_mode"] in fixture["enums"]["binding_mode"]
        assert case["expected_outcome"] in fixture["enums"]["expected_outcome"]
        if case["binding_mode"] != "valid":
            assert case["expected_outcome"] == "safe_stop"

    result = fixture["result_example"]
    assert set(result) == set(fixture["required_result_fields"])
    assert result["outcome"] in fixture["enums"]["outcome"]
    assert result["handoff_size_bytes"] < result["full_trace_size_bytes"]
    assert result["claim_treated_as_verified"] is False
    assert result["critical_trust_boundary_violation"] is False
    assert thresholds == {
        "resume_success_rate": 0.8,
        "broken_binding_safe_stop_rate": 1.0,
        "critical_trust_boundary_violations": 0,
    }


def test_release_smoke_indexes_freeze_valid_and_invalid_binding_paths() -> None:
    trace_bytes = (FIXTURE_ROOT / "master-trace.md").read_bytes()
    binding = {
        "trace_evidence_id": "E-0001",
        "trace_manifest_path": ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json",
        "trace_member_path": "trace.md",
        "trace_stored_path": ".project-loop/evidence/adhoc-files/e-0001/01-trace.md",
        "recorded_trace_sha256": hashlib.sha256(trace_bytes).hexdigest(),
        "trace_bytes": trace_bytes,
    }
    valid = json.loads(
        (FIXTURE_ROOT / "release-smoke-valid-trace-binding.json").read_text(encoding="utf-8")
    )
    invalid = json.loads(
        (FIXTURE_ROOT / "release-smoke-invalid-trace-binding.json").read_text(encoding="utf-8")
    )

    assert validate_intent_index_binding(valid, **binding)["status"] == "valid"
    invalid_result = validate_intent_index_binding(invalid, **binding)
    assert invalid_result["status"] == "invalid"
    assert [item["code"] for item in invalid_result["diagnostics"]] == [
        "trace_hash_mismatch"
    ]
