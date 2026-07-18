from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "layered_harness_ablation_v0"
    / "layered-harness-ablation-fixture.json"
)
COHORT_PATH = ROOT / "docs" / "evaluation" / "layered-harness-ablation-cohort.json"
RUNBOOK_PATH = ROOT / "docs" / "evaluation" / "layered-harness-ablation-runbook.md"

BASELINE_FULL = "7fa22b23917a7847dee56d574d16a14d9649e086"
TREATMENT_FULL = "5ce17ec202ad16fb67d2514fcd95e508ec489ca1"
CASE_IDS = [f"LHA-{index:03d}" for index in range(1, 9)]
LAYER_SPLIT = {"single_session": 3, "resume_handoff": 3, "human_gate": 2}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_show_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
    )


def test_fixture_freezes_eight_cases_metrics_and_pareto_rule() -> None:
    fixture = _load(FIXTURE_PATH)

    assert fixture["contract_version"] == "layered-harness-ablation-fixture/v0"
    assert fixture["comparison"]["baseline"]["commit"] == "7fa22b2"
    assert fixture["comparison"]["baseline"]["commit_full"] == BASELINE_FULL
    assert fixture["comparison"]["treatment"]["commit"] == "5ce17ec"
    assert fixture["comparison"]["treatment"]["commit_full"] == TREATMENT_FULL

    cases = fixture["cases"]
    assert isinstance(cases, list)
    assert len(cases) == 8
    assert [case["id"] for case in cases] == CASE_IDS
    assert Counter(case["layer"] for case in cases) == LAYER_SPLIT

    required = set(fixture["required_case_fields"])
    for case in cases:
        assert required.issubset(case.keys())
        assert case["literal_objective"].strip()
        assert case["prompt"].strip()
        assert case["acceptance_oracle"]["must"]
        assert case["acceptance_oracle"]["fail_if"]
        assert case["fixture_state"]
        assert case["allowed_context"]
        assert case["forbidden_context"]

    quality_ids = {metric["id"] for metric in fixture["quality_metrics"]}
    cost_ids = {metric["id"] for metric in fixture["cost_metrics"]}
    assert quality_ids == {
        "acceptance_success",
        "target_route_accuracy",
        "resume_handoff_accuracy",
        "current_proof_classification_accuracy",
        "human_gate_integrity",
        "unintended_mutation_count",
        "human_intervention_count",
    }
    assert cost_ids == {
        "tool_command_calls",
        "wall_clock_seconds",
        "input_tokens",
        "output_tokens",
        "loaded_skill_bytes",
    }

    rule = fixture["recommendation_rule"]
    assert rule["id"] == "pareto_proceed_v0"
    assert rule["options"] == ["proceed", "modify", "stop"]
    assert "no_paired_quality_regression" in rule["proceed_requires_all"]
    assert "at_least_one_strict_fully_observed_cost_improvement" in rule[
        "proceed_requires_all"
    ]
    assert rule["denominator_rules"]["include_failed"] is True
    assert rule["denominator_rules"]["include_safe_stopped"] is True
    assert rule["token_conclusion_rules"]["unavailable_is_null_never_estimated"] is True
    assert rule["cost_tolerances"]["wall_clock_seconds"]["max_relative_increase"] == 0.1
    assert rule["cost_tolerances"]["tool_command_calls"]["max_absolute_increase"] == 0

    example = fixture["result_example"]
    assert example["notes"].startswith("Fixture example only")
    assert example["input_tokens"] is None
    assert example["output_tokens"] is None
    for field in fixture["required_result_fields"]:
        assert field in example


def test_cohort_is_hash_pinned_and_has_sixteen_prepared_arms() -> None:
    fixture = _load(FIXTURE_PATH)
    cohort = _load(COHORT_PATH)

    assert cohort["contract_version"] == "layered-harness-ablation-cohort/v1"
    assert cohort["cohort_id"] == "LHA-20260718-01"
    assert cohort["status"] == "prepared_pending_independent_session_authorization"
    assert cohort["fixture"]["path"] == str(
        FIXTURE_PATH.relative_to(ROOT)
    ).replace("\\", "/")
    assert (
        cohort["fixture"]["sha256"]
        == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    )
    assert RUNBOOK_PATH.is_file()
    assert cohort["runbook"]["path"] == str(RUNBOOK_PATH.relative_to(ROOT)).replace(
        "\\", "/"
    )

    assert cohort["comparison"]["baseline"]["commit_full"] == BASELINE_FULL
    assert cohort["comparison"]["treatment"]["commit_full"] == TREATMENT_FULL
    assert cohort["sample_size"] == {
        "cases": 8,
        "arms": 16,
        "layer_split": LAYER_SPLIT,
    }
    assert cohort["thresholds"]["recommendation_rule_id"] == "pareto_proceed_v0"
    assert cohort["thresholds"] == {
        **cohort["thresholds"],
        "critical_gate_violations": 0,
        "recommendation_options": ["proceed", "modify", "stop"],
    }
    assert cohort["thresholds"]["cost_tolerances"] == fixture["recommendation_rule"][
        "cost_tolerances"
    ]
    assert cohort["thresholds"]["proceed_requires_all"] == fixture[
        "recommendation_rule"
    ]["proceed_requires_all"]

    cases = cohort["cases"]
    fixture_cases = fixture["cases"]
    assert [case["id"] for case in cases] == [case["id"] for case in fixture_cases]
    assert Counter(case["layer"] for case in cases) == LAYER_SPLIT
    for concrete, frozen in zip(cases, fixture_cases, strict=True):
        assert concrete["id"] == frozen["id"]
        assert concrete["layer"] == frozen["layer"]
        assert concrete["title"] == frozen["title"]
        assert concrete["literal_objective"] == frozen["literal_objective"]
        assert concrete["prompt"] == frozen["prompt"]
        assert concrete["fixture_state_kind"] == frozen["fixture_state"]["kind"]
        assert concrete["quality_dimensions"] == frozen["quality_dimensions"]

    arms = cohort["arms"]
    assert len(arms) == 16
    assert len({arm["arm_id"] for arm in arms}) == 16
    assert all(arm["independent_session"] is True for arm in arms)
    assert all(arm["status"] == "prepared_not_executed" for arm in arms)
    assert all(arm["result_path"] is None for arm in arms)
    assert all(arm["session_ref"] is None for arm in arms)

    expected_arm_ids = [
        f"{case_id}-{condition}"
        for case_id in CASE_IDS
        for condition in ("baseline", "treatment")
    ]
    assert [arm["arm_id"] for arm in arms] == expected_arm_ids

    for arm in arms:
        if arm["condition"] == "baseline":
            assert arm["commit"] == "7fa22b2"
            assert arm["commit_full"] == BASELINE_FULL
            assert arm["loaded_skill_bytes"] == 17603
        else:
            assert arm["condition"] == "treatment"
            assert arm["commit"] == "5ce17ec"
            assert arm["commit_full"] == TREATMENT_FULL
            assert arm["loaded_skill_bytes"] == 17433

    assert cohort["results"]["status"] == "not_started"
    assert cohort["results"]["path"] is None
    assert "fabricat" in cohort["results"]["note"].lower()
    assert not any(key.startswith("result_") for key in cohort if key != "results")
    assert cohort["execution_authorization"] == {
        "independent_agent_sessions": False,
        "network_model_provider_runs": False,
        "paid_runs": False,
        "result_fabrication": False,
        "runtime_code_changes_in_freeze_slice": False,
        "arms_planned": 16,
        "note": cohort["execution_authorization"]["note"],
    }
    assert cohort["execution_authorization"]["result_fabrication"] is False


def test_loaded_skill_bytes_match_arm_commits() -> None:
    fixture = _load(FIXTURE_PATH)
    cohort = _load(COHORT_PATH)
    skill_path = ".agents/skills/project-control-loop/SKILL.md"

    for condition, commit in (
        ("baseline", BASELINE_FULL),
        ("treatment", TREATMENT_FULL),
    ):
        payload = _git_show_bytes(commit, skill_path)
        expected = fixture["loaded_skill_bytes_by_condition"][condition]
        assert expected["path"] == skill_path
        assert expected["bytes"] == len(payload)
        assert expected["sha256"] == hashlib.sha256(payload).hexdigest()
        assert cohort["loaded_skill_bytes_by_condition"][condition] == expected


def test_runbook_names_frozen_commits_cases_and_no_fabrication() -> None:
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "layered-harness-ablation-cohort.json" in text
    assert "7fa22b2" in text
    assert "5ce17ec" in text
    assert "LHA-001" in text and "LHA-008" in text
    assert "16 independent" in lowered or "exactly 16" in lowered
    assert "pareto_proceed_v0" in text
    assert "fabricat" in lowered
    assert "not yet authorized" in lowered
    for case_id in CASE_IDS:
        assert case_id in text


def test_cohort_rejects_implicit_results_and_runtime_scope_creep() -> None:
    cohort = _load(COHORT_PATH)
    fixture = _load(FIXTURE_PATH)

    # Freeze slice must not claim execution or Phase 5 proceed.
    assert cohort["status"].startswith("prepared_")
    assert all(arm["status"] == "prepared_not_executed" for arm in cohort["arms"])
    assert fixture["recommendation_rule"]["phase5_gate"].startswith(
        "Do not implement Phase 5"
    )
    assert "Do not fabricate arm results" in " ".join(fixture["non_goals"])
    assert "Do not change runtime code" in " ".join(fixture["non_goals"])

    # No arm may point at a fabricated result artifact path yet.
    result_dir = ROOT / "docs" / "evaluation" / "layered-harness-ablation-results"
    assert not result_dir.exists()
