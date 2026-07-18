from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


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

PCL_ID_PATTERNS = {
    "G": re.compile(r"^G-[0-9]{4,}$"),
    "T": re.compile(r"^T-[0-9]{4,}$"),
    "F": re.compile(r"^F-[0-9]{4,}$"),
    "US": re.compile(r"^US-[0-9]{4,}$"),
    "DEC": re.compile(r"^DEC-[0-9]{4,}$"),
    "E": re.compile(r"^E-[0-9]{4,}$"),
}
NON_ENTITY_PRODUCES = {"validation_fixture", "packet", "TASK-NOT-A-REAL-ID"}


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains a repeated key."""


def _load_rejecting_duplicate_keys(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    duplicates: list[str] = []

    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
            out[key] = value
        return out

    payload = json.loads(text, object_pairs_hook=object_pairs_hook)
    if duplicates:
        raise DuplicateKeyError(
            f"{path}: duplicate JSON keys: {sorted(set(duplicates))}"
        )
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} must decode to an object")
    return payload


def _git_rev_parse(commit: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", commit],
        cwd=ROOT,
        text=True,
    ).strip()


def _git_show_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
    )


def _assert_pcl_id(value: str) -> None:
    if value in NON_ENTITY_PRODUCES:
        return
    prefix = value.split("-", 1)[0]
    pattern = PCL_ID_PATTERNS.get(prefix)
    assert pattern is not None and pattern.match(value), f"invalid PCL id: {value!r}"


def _walk_ids(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, str) and re.match(r"^(G|T|F|US|DEC|E)-", node):
        found.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            found.extend(_walk_ids(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_ids(value))
    return found


def test_json_artifacts_reject_duplicate_keys() -> None:
    fixture = _load_rejecting_duplicate_keys(FIXTURE_PATH)
    cohort = _load_rejecting_duplicate_keys(COHORT_PATH)
    assert fixture["contract_version"] == "layered-harness-ablation-fixture/v0"
    assert cohort["contract_version"] == "layered-harness-ablation-cohort/v1"

    # Cost-tolerance objects use a single relative limit key name each.
    for metric, tolerance in fixture["recommendation_rule"]["cost_tolerances"].items():
        assert "max_relative_increase" not in tolerance, metric
        assert "relative_increase_limit" in tolerance, metric

    case_ids = [case["id"] for case in fixture["cases"]]
    assert case_ids == CASE_IDS
    assert len(case_ids) == len(set(case_ids))
    assert [case["id"] for case in cohort["cases"]] == CASE_IDS


def test_fixture_freezes_eight_cases_metrics_and_pareto_rule() -> None:
    fixture = _load_rejecting_duplicate_keys(FIXTURE_PATH)

    assert fixture["comparison"]["baseline"]["commit"] == "7fa22b2"
    assert fixture["comparison"]["baseline"]["commit_full"] == BASELINE_FULL
    assert fixture["comparison"]["treatment"]["commit"] == "5ce17ec"
    assert fixture["comparison"]["treatment"]["commit_full"] == TREATMENT_FULL
    assert _git_rev_parse("7fa22b2") == BASELINE_FULL
    assert _git_rev_parse("5ce17ec") == TREATMENT_FULL

    cases = fixture["cases"]
    assert len(cases) == 8
    assert Counter(case["layer"] for case in cases) == LAYER_SPLIT

    required = set(fixture["required_case_fields"])
    for case in cases:
        assert required.issubset(case.keys())
        assert case["literal_objective"].strip()
        assert case["prompt"].strip()
        assert case["acceptance_oracle"]["must"]
        assert case["acceptance_oracle"]["fail_if"]
        state = case["fixture_state"]
        assert state["steps"]
        assert state["expected_ids"]
        assert state["allocation_rule"]
        for entity_id in state["expected_ids"].values():
            _assert_pcl_id(entity_id)
        for step in state["steps"]:
            if "produces" in step:
                _assert_pcl_id(step["produces"])
        for entity_id in _walk_ids(state.get("roles", {})):
            _assert_pcl_id(entity_id)

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
    assert rule["runtime_cost_metrics"] == [
        "tool_command_calls",
        "wall_clock_seconds",
        "input_tokens",
        "output_tokens",
    ]
    assert rule["supporting_context_metrics"] == ["loaded_skill_bytes"]
    assert rule["cost_metrics_eligible_for_proceed_improvement"] == rule[
        "runtime_cost_metrics"
    ]
    assert "loaded_skill_bytes" not in rule["cost_metrics_eligible_for_proceed_improvement"]
    assert rule["skill_bytes_policy"]["may_authorize_proceed_alone"] is False
    assert (
        "at_least_one_strict_fully_observed_runtime_cost_improvement"
        in rule["proceed_requires_all"]
    )
    assert (
        "at_least_one_strict_fully_observed_cost_improvement"
        not in rule["proceed_requires_all"]
    )
    assert rule["cost_tolerances"]["loaded_skill_bytes"][
        "cannot_satisfy_proceed_improvement_requirement"
    ] is True
    assert rule["cost_tolerances"]["wall_clock_seconds"]["relative_increase_limit"] == 0.1
    assert rule["denominator_rules"]["include_failed"] is True
    assert rule["token_conclusion_rules"]["unavailable_is_null_never_estimated"] is True
    assert "loaded_skill_bytes reduction alone" in rule["phase5_gate"]

    example = fixture["result_example"]
    assert example["notes"].startswith("Fixture example only")
    assert example["input_tokens"] is None
    for field in fixture["required_result_fields"]:
        assert field in example


def test_prepared_arms_are_sixteen_paired_with_agent_plan() -> None:
    fixture = _load_rejecting_duplicate_keys(FIXTURE_PATH)
    cohort = _load_rejecting_duplicate_keys(COHORT_PATH)

    for payload in (fixture, cohort):
        arms = payload["prepared_arms"]
        assert len(arms) == 16
        assert len({arm["arm_id"] for arm in arms}) == 16
        assert [arm["arm_id"] for arm in arms] == [
            f"{case_id}-{condition}"
            for case_id in CASE_IDS
            for condition in ("baseline", "treatment")
        ]
        for field in fixture["required_arm_fields"]:
            for arm in arms:
                assert field in arm

        for index in range(0, 16, 2):
            baseline = arms[index]
            treatment = arms[index + 1]
            assert baseline["case_id"] == treatment["case_id"]
            assert baseline["condition"] == "baseline"
            assert treatment["condition"] == "treatment"
            assert baseline["planned_agent_type"] == treatment["planned_agent_type"]
            assert baseline["planned_runtime"] == treatment["planned_runtime"]
            assert baseline["planned_model"] == treatment["planned_model"]
            assert baseline["independent_session"] is True
            assert treatment["independent_session"] is True
            assert baseline["status"] == "prepared_not_executed"
            assert treatment["status"] == "prepared_not_executed"
            assert baseline["commit_full"] == BASELINE_FULL
            assert treatment["commit_full"] == TREATMENT_FULL
            assert baseline["loaded_skill_bytes"] == 17603
            assert treatment["loaded_skill_bytes"] == 17433

    cases_by_id = {case["id"]: case for case in fixture["cases"]}
    for arm in fixture["prepared_arms"]:
        layer = cases_by_id[arm["case_id"]]["layer"]
        if layer == "single_session":
            assert arm["planned_agent_type"] == "grok"
            assert arm["planned_model"] == "grok-4.5"
        else:
            assert layer in {"resume_handoff", "human_gate"}
            assert arm["planned_agent_type"] == "codex"
            assert arm["planned_model"] == "codex"
        assert arm["planned_runtime"] == "cockpit"


def test_cohort_is_hash_pinned_and_has_no_fabricated_results() -> None:
    fixture = _load_rejecting_duplicate_keys(FIXTURE_PATH)
    cohort = _load_rejecting_duplicate_keys(COHORT_PATH)

    assert cohort["cohort_id"] == "LHA-20260718-01"
    assert cohort["status"] == "prepared_pending_independent_session_authorization"
    assert cohort["fixture"]["path"] == str(FIXTURE_PATH.relative_to(ROOT)).replace(
        "\\", "/"
    )
    assert (
        cohort["fixture"]["sha256"]
        == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    )
    assert RUNBOOK_PATH.is_file()
    assert cohort["sample_size"] == {
        "cases": 8,
        "arms": 16,
        "layer_split": LAYER_SPLIT,
    }
    assert "arms" not in cohort or "prepared_arms" in cohort
    assert cohort["thresholds"]["recommendation_rule_id"] == "pareto_proceed_v0"
    assert cohort["thresholds"]["cost_tolerances"] == fixture["recommendation_rule"][
        "cost_tolerances"
    ]
    assert cohort["thresholds"]["proceed_requires_all"] == fixture[
        "recommendation_rule"
    ]["proceed_requires_all"]
    assert cohort["thresholds"]["skill_bytes_policy"]["may_authorize_proceed_alone"] is False
    assert (
        "loaded_skill_bytes"
        not in cohort["thresholds"]["cost_metrics_eligible_for_proceed_improvement"]
    )

    for concrete, frozen in zip(cohort["cases"], fixture["cases"], strict=True):
        assert concrete["id"] == frozen["id"]
        assert concrete["layer"] == frozen["layer"]
        assert concrete["prompt"] == frozen["prompt"]
        assert concrete["literal_objective"] == frozen["literal_objective"]
        assert concrete["expected_ids"] == frozen["fixture_state"]["expected_ids"]
        assert concrete["setup_steps"] == frozen["fixture_state"]["steps"]
        assert concrete["pair_plan"] == fixture["pair_agent_plan"][frozen["layer"]]

    assert cohort["results"]["status"] == "not_started"
    assert cohort["results"]["path"] is None
    assert "fabricat" in cohort["results"]["note"].lower()
    assert cohort["execution_authorization"]["result_fabrication"] is False
    assert cohort["execution_authorization"]["independent_agent_sessions"] is False


def test_loaded_skill_bytes_match_arm_commits_and_cannot_authorize_alone() -> None:
    fixture = _load_rejecting_duplicate_keys(FIXTURE_PATH)
    cohort = _load_rejecting_duplicate_keys(COHORT_PATH)
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

    assert fixture["recommendation_rule"]["skill_bytes_policy"][
        "may_authorize_proceed_alone"
    ] is False
    assert "Phase 5" in fixture["recommendation_rule"]["phase5_gate"]


def test_runbook_covers_arms_ids_pareto_and_skill_bytes_limit() -> None:
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "layered-harness-ablation-cohort.json" in text
    assert "prepared_arms" in text
    assert "7fa22b2" in text and BASELINE_FULL in text
    assert "5ce17ec" in text and TREATMENT_FULL in text
    assert "^T-[0-9]{4,}$" in text
    assert "^G-[0-9]{4,}$" in text
    assert "TASK-NOT-A-REAL-ID" in text
    assert "grok" in lowered and "codex" in lowered
    assert "single-session" in lowered or "single_session" in lowered
    assert "pareto_proceed_v0" in text
    assert "runtime-cost" in lowered or "runtime cost" in lowered
    assert "loaded_skill_bytes" in lowered
    assert "must not yield `proceed`" in lowered or "must not yield proceed" in lowered
    assert "phase 5" in lowered
    assert "duplicate" in lowered
    assert "not yet authorized" in lowered
    for case_id in CASE_IDS:
        assert case_id in text


def test_malformed_target_case_keeps_valid_seed_ids() -> None:
    fixture = _load_rejecting_duplicate_keys(FIXTURE_PATH)
    case = next(item for item in fixture["cases"] if item["id"] == "LHA-006")
    state = case["fixture_state"]
    assert state["malformed_target"] == "TASK-NOT-A-REAL-ID"
    assert state["expected_ids"] == {"goal": "G-0001", "task": "T-0001"}
    assert state["valid_contrast_targets"] == {"goal": "G-0001", "task": "T-0001"}
    assert case["id"] == "LHA-006"
    assert sum(1 for item in fixture["cases"] if item["id"] == "LHA-006") == 1
