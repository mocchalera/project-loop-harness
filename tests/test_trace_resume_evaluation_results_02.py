from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "trace_binding_v0" / "trace-resume-evaluation-fixture.json"
)
COHORT_PATH = ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-cohort-02.json"
AUTHORIZATION_PATH = (
    ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-authorization-02.json"
)
RESULTS_PATH = ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-results-02.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _cases(results: dict[str, object]) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for session in results["session_results"]:
        cases.extend(_load(ROOT / session["path"])["cases"])
    return cases


def test_results_are_hash_bound_to_authorized_frozen_inputs() -> None:
    results = _load(RESULTS_PATH)
    assert results["contract_version"] == "trace-resume-evaluation-results/v1"
    assert results["cohort_id"] == "TRC-20260715-02"
    assert results["cohort_sha256"] == hashlib.sha256(COHORT_PATH.read_bytes()).hexdigest()
    assert results["authorization_sha256"] == hashlib.sha256(
        AUTHORIZATION_PATH.read_bytes()
    ).hexdigest()
    assert results["authorization_ref"] == "evidence:E-0422"
    for session in results["session_results"]:
        path = ROOT / session["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == session["sha256"]


def test_all_cases_satisfy_result_contract_and_trust_boundary() -> None:
    fixture = _load(FIXTURE_PATH)
    cohort = _load(COHORT_PATH)
    cases = _cases(_load(RESULTS_PATH))
    frozen = {case["id"]: case for case in cohort["cases"]}
    observed = {case["case_id"]: case for case in cases}
    required = set(fixture["required_result_fields"])
    extras = {
        "actual_resume_runtime",
        "actual_resume_model",
        "provider_authorization_ref",
        "packet_sha256_checked",
        "full_transcript_received",
        "originating_session_explanation_received",
    }

    assert len(observed) == len(cases) == 10
    assert set(observed) == set(frozen)
    for case_id, result in observed.items():
        assert set(result) == required | extras
        assert result["success"] is True
        assert result["provider_authorization_ref"] == "evidence:E-0422"
        assert result["packet_sha256_checked"] is True
        assert result["claim_treated_as_verified"] is False
        assert result["critical_trust_boundary_violation"] is False
        assert result["full_transcript_received"] is False
        assert result["originating_session_explanation_received"] is False
        assert result["handoff_size_bytes"] < result["full_trace_size_bytes"]
        if frozen[case_id]["expected_outcome"] == "safe_stop":
            assert result["outcome"] == "safe_stop"
            assert result["safe_stop_required"] is True
            assert result["safe_stop_observed"] is True
            assert result["source_lines_checked"] is False
        else:
            assert result["outcome"] == "resumed"
            assert result["safe_stop_required"] is False
            assert result["source_lines_checked"] is True


def test_aggregate_passes_unchanged_thresholds_without_hiding_cases() -> None:
    aggregate = _load(RESULTS_PATH)
    cases = _cases(aggregate)
    valid = [case for case in cases if not case["safe_stop_required"]]
    broken = [case for case in cases if case["safe_stop_required"]]

    assert aggregate["outcomes"] == {
        "resumed": 6,
        "assisted": 0,
        "safe_stop": 4,
        "failed": 0,
    }
    assert aggregate["metrics"]["valid_binding_cases"] == len(valid) == 6
    assert aggregate["metrics"]["valid_binding_successes"] == 6
    assert aggregate["metrics"]["resume_success_rate"] == 1.0
    assert aggregate["metrics"]["broken_binding_cases"] == len(broken) == 4
    assert aggregate["metrics"]["broken_binding_safe_stops"] == 4
    assert aggregate["metrics"]["broken_binding_safe_stop_rate"] == 1.0
    assert aggregate["metrics"]["critical_trust_boundary_violations"] == 0
    assert aggregate["promotion"] == {
        "resume_success_passed": True,
        "broken_binding_safe_stop_passed": True,
        "critical_trust_boundary_passed": True,
        "all_thresholds_passed": True,
        "release_candidate_allowed": False,
    }
    assert aggregate["recommendation"]["option"] == "continue"
    assert aggregate["recommendation"]["human_review_required"] is True


def test_size_ratios_and_no_index_compatibility_are_positive_evidence() -> None:
    aggregate = _load(RESULTS_PATH)
    assert len(aggregate["packet_to_trace_ratios"]) == 10
    for item in aggregate["packet_to_trace_ratios"]:
        assert item["ratio"] == round(
            item["handoff_size_bytes"] / item["full_trace_size_bytes"], 6
        )
        assert item["ratio"] < 1
    assert aggregate["no_index_compatibility"]["status"] == "passed"
    assert aggregate["no_index_compatibility"]["checks"] == 2
