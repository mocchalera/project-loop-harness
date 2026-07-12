from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "docs" / "evaluation" / "v0.5.0-council-cohort.json"
RESULTS = ROOT / "docs" / "evaluation" / "v0.5.0-council-results.json"


def test_council_evaluation_cohort_is_frozen_before_results() -> None:
    value = json.loads(COHORT.read_text(encoding="utf-8"))
    cases = value["cases"]
    assert value["contract_version"] == "council-evaluation-cohort/v1"
    assert value["sample_size"] == len(cases) == 12
    assert len({item["id"] for item in cases}) == 12
    assert {item["category"] for item in cases} == {
        "clear",
        "ambiguous",
        "repository_analysis",
        "migration_auth_security",
        "product_decision",
    }
    assert value["baseline"]["direct_is_default"] is True
    assert value["baseline"]["offline_fixture_is_not_quality_evidence"] is True
    assert value["success_thresholds"]["invalid_partial_budget_safe_stop_rate"] == 1.0
    assert value["success_thresholds"]["real_provider_paired_sample_required_for_adoption"] == 10
    assert not any(key.startswith("result") for key in value)


def test_council_results_preserve_frozen_cohort_and_safe_stop_threshold() -> None:
    cohort = json.loads(COHORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert results["cohort_sha256"] == hashlib.sha256(COHORT.read_bytes()).hexdigest()
    assert results["cohort_id"] == cohort["cohort_id"]
    assert results["sample_size"] == cohort["sample_size"]
    assert [item["id"] for item in results["cases"]] == [
        item["id"] for item in cohort["cases"]
    ]
    assert results["safe_stop"]["rate"] == 1.0
    assert results["safe_stop"]["eligible_cases"] == results["safe_stop"]["safe_cases"]
    assert results["failure_modes"]["invalid_bundle_persisted"] == 0
    assert results["clear_task_insertion"]["unnecessary_council_count"] == 0
    assert results["quality"]["paired_real_provider_sample_size"] == 0
    assert results["quality"]["conclusion"] == "unavailable_offline_fixture_is_not_quality_evidence"
    assert results["recommendation"]["option"] == "continue_experiment"
    assert results["recommendation"]["default_change"] is False
