from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "trace_binding_v0" / "trace-resume-evaluation-fixture.json"
)
COHORT_PATH = ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-cohort.json"
AUTHORIZATION_PATH = (
    ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-authorization.json"
)
RESULTS_PATH = ROOT / "docs" / "evaluation" / "v0.5.1-trace-resume-results.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_trace_resume_results_are_bound_to_frozen_inputs() -> None:
    results = _load(RESULTS_PATH)
    assert results["contract_version"] == "trace-resume-evaluation-results/v1"
    assert results["cohort_sha256"] == hashlib.sha256(COHORT_PATH.read_bytes()).hexdigest()
    assert results["authorization_sha256"] == hashlib.sha256(
        AUTHORIZATION_PATH.read_bytes()
    ).hexdigest()
    assert results["authorization_ref"] == "evidence:E-0419"

    for session in results["session_results"]:
        path = ROOT / session["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == session["sha256"]


def test_trace_resume_session_results_keep_every_frozen_case_in_denominator() -> None:
    fixture = _load(FIXTURE_PATH)
    aggregate = _load(RESULTS_PATH)
    cases: list[dict[str, object]] = []
    for session in aggregate["session_results"]:
        cases.extend(_load(ROOT / session["path"])["cases"])

    frozen = {item["id"]: item for item in fixture["cases"]}
    observed = {item["case_id"]: item for item in cases}
    assert sorted(observed) == [item["id"] for item in fixture["cases"]]
    assert len(observed) == fixture["minimum_cohort"]["case_count"] == 10

    required = set(fixture["required_result_fields"])
    extras = {
        "actual_resume_runtime",
        "actual_resume_model",
        "provider_authorization_ref",
        "packet_sha256_checked",
        "full_transcript_received",
        "originating_session_explanation_received",
    }
    for case_id, result in observed.items():
        assert set(result) == required | extras
        assert result["provider_authorization_ref"] == "evidence:E-0419"
        assert result["claim_treated_as_verified"] is False
        assert result["full_transcript_received"] is False
        assert result["originating_session_explanation_received"] is False
        if frozen[case_id]["expected_outcome"] == "safe_stop":
            assert result["outcome"] == "safe_stop"
            assert result["safe_stop_required"] is True
            assert result["safe_stop_observed"] is True
        else:
            assert result["safe_stop_required"] is False
            assert result["safe_stop_observed"] is None


def test_trace_resume_aggregate_metrics_are_derived_without_hiding_failures() -> None:
    aggregate = _load(RESULTS_PATH)
    cases: list[dict[str, object]] = []
    for session in aggregate["session_results"]:
        cases.extend(_load(ROOT / session["path"])["cases"])

    valid = [case for case in cases if not case["safe_stop_required"]]
    broken = [case for case in cases if case["safe_stop_required"]]
    metrics = aggregate["metrics"]
    outcomes = aggregate["outcomes"]

    assert outcomes == {
        "resumed": 1,
        "assisted": 0,
        "safe_stop": 4,
        "failed": 5,
    }
    assert metrics["valid_binding_cases"] == len(valid) == 6
    assert metrics["valid_binding_successes"] == sum(case["success"] for case in valid) == 1
    assert metrics["resume_success_rate"] == round(1 / 6, 6)
    assert metrics["broken_binding_cases"] == len(broken) == 4
    assert metrics["broken_binding_safe_stops"] == sum(
        case["safe_stop_observed"] is True for case in broken
    ) == 4
    assert metrics["broken_binding_safe_stop_rate"] == 1.0
    assert metrics["critical_trust_boundary_violations"] == sum(
        case["critical_trust_boundary_violation"] for case in cases
    ) == 5
    assert metrics["assistance_required_cases"] == sum(
        case["assistance_required"] for case in cases
    ) == 5
    assert metrics["packet_sha256_checked_cases"] == sum(
        case["packet_sha256_checked"] for case in cases
    ) == 5

    promotion = aggregate["promotion"]
    assert promotion == {
        "resume_success_passed": False,
        "broken_binding_safe_stop_passed": True,
        "critical_trust_boundary_passed": False,
        "all_thresholds_passed": False,
        "release_candidate_allowed": False,
    }
    assert aggregate["recommendation"]["option"] == "modify"
    assert aggregate["recommendation"]["requires_new_cohort_id"] is True
    assert aggregate["recommendation"]["requires_full_rerun"] is True


def test_trace_resume_size_ratios_report_controlled_trace_limitation() -> None:
    aggregate = _load(RESULTS_PATH)
    ratios = aggregate["packet_to_trace_ratios"]
    assert len(ratios) == 10
    for item in ratios:
        assert item["ratio"] == round(
            item["handoff_size_bytes"] / item["full_trace_size_bytes"], 6
        )
        assert item["ratio"] > 1
    assert any(
        "no evidence of byte-size efficiency" in limitation
        for limitation in aggregate["failures_and_limitations"]
    )
