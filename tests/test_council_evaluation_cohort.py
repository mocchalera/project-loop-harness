from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "docs" / "evaluation" / "v0.5.0-council-cohort.json"


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
