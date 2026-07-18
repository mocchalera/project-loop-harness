from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evaluate_layered_harness_ablation.py"
FIXTURE = (
    ROOT
    / "tests/fixtures/layered_harness_ablation_v0/layered-harness-ablation-fixture.json"
)
SCENARIOS = FIXTURE.parent / "evaluator-scenarios.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _records(*, runtime_improvement: bool = True) -> list[dict[str, object]]:
    fixture = _fixture()
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenario_name = (
        "proceed_with_runtime_improvement"
        if runtime_improvement
        else "modify_with_skill_bytes_only"
    )
    scenario = scenarios["scenarios"][scenario_name]
    actual_models = scenarios["actual_models_by_agent_type"]
    cases = {case["id"]: case for case in fixture["cases"]}
    records: list[dict[str, object]] = []
    for arm in fixture["prepared_arms"]:
        case = cases[arm["case_id"]]
        treatment = arm["condition"] == "treatment"
        records.append(
            {
                "arm_id": arm["arm_id"],
                "case_id": arm["case_id"],
                "condition": arm["condition"],
                "commit_full": arm["commit_full"],
                "session_ref": f"cockpit:test-fixture:{arm['arm_id']}",
                "outcome": "accepted",
                "acceptance_success": True,
                "target_route_accuracy": True,
                "resume_handoff_accuracy": (
                    True if "resume_handoff_accuracy" in case["quality_dimensions"] else None
                ),
                "current_proof_classification_accuracy": (
                    True
                    if "current_proof_classification_accuracy" in case["quality_dimensions"]
                    else None
                ),
                "human_gate_integrity": True,
                "unintended_mutation_count": 0,
                "human_intervention_count": 0,
                "critical_gate_violation": False,
                "tool_command_calls": scenario[
                    "treatment_tool_command_calls"
                    if treatment
                    else "baseline_tool_command_calls"
                ],
                "wall_clock_seconds": scenario["wall_clock_seconds"],
                "input_tokens": scenario["input_tokens"],
                "output_tokens": scenario["output_tokens"],
                "loaded_skill_bytes": arm["loaded_skill_bytes"],
                "safe_stop_observed": None,
                "contaminated": False,
                "notes": "Deterministic synthetic test fixture; not an ablation run.",
                "evidence_paths": [],
                "actual_agent_type": arm["planned_agent_type"],
                "actual_runtime": arm["planned_runtime"],
                "actual_model": actual_models[arm["planned_agent_type"]],
            }
        )
    return records


def _write_records(directory: Path, records: list[dict[str, object]]) -> None:
    directory.mkdir()
    for index, record in enumerate(records):
        (directory / f"result-{index:02d}.json").write_text(
            json.dumps(record, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_authorization(path: Path, **updates: object) -> dict[str, object]:
    fixture = _fixture()
    authorization: dict[str, object] = {
        "contract_version": "layered-harness-ablation-authorization/v1",
        "cohort_id": "LHA-20260718-01",
        "cohort_sha256": "2726dc760e0dfcb46494d4c9072601868d9b6edc7d7fe13e15378ffdd7a51080",
        "authorized_arm_ids": sorted(arm["arm_id"] for arm in fixture["prepared_arms"]),
        "independent_cockpit_sessions": True,
        "network_model_provider_runs": True,
        "authorized_agent_types": ["codex", "grok"],
        "data_class": "repository source and frozen evaluation context",
        "budget": {
            "currency": "USD",
            "max_amount": 100,
            "paid_runs_allowed": True,
        },
        "cost_policy": "Stop before exceeding max_amount; never estimate provider tokens.",
        "authorized_by": "human:test-fixture",
        "authorized_at": "2026-07-18T00:00:00Z",
        "expires_at": "2099-01-02T00:00:00Z",
    }
    authorization.update(updates)
    path.write_text(json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8")
    return authorization


def test_prepare_writes_sixteen_deterministic_hash_bound_arm_packets(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    authorization_path = tmp_path / "authorization.json"
    _write_authorization(authorization_path)

    first = _run(
        "prepare",
        "--output-dir",
        str(first_dir),
        "--authorization",
        str(authorization_path),
    )
    second = _run(
        "prepare",
        "--output-dir",
        str(second_dir),
        "--authorization",
        str(authorization_path),
    )

    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    manifest = json.loads(first.stdout)
    assert manifest["packet_count"] == 16
    assert len(list(first_dir.glob("LHA-*.json"))) == 16
    for item in manifest["packets"]:
        first_bytes = (first_dir / item["path"]).read_bytes()
        second_bytes = (second_dir / item["path"]).read_bytes()
        assert first_bytes == second_bytes
        assert hashlib.sha256(first_bytes).hexdigest() == item["sha256"]
    packet = json.loads((first_dir / "LHA-004-treatment.json").read_text())
    assert packet["arm"]["commit_full"] == "5ce17ec202ad16fb67d2514fcd95e508ec489ca1"
    assert packet["case"]["id"] == "LHA-004"
    assert packet["result_contract"]["result_path"] == "LHA-004-treatment.json"
    assert packet["authorization"]["authorized"] is True
    assert packet["authorization"]["receipt_sha256"] == hashlib.sha256(
        authorization_path.read_bytes()
    ).hexdigest()
    assert packet["frozen_preparation_boundary"]["independent_agent_sessions"] is False


def test_prepare_rejects_missing_or_incomplete_execution_authorization(tmp_path: Path) -> None:
    missing = _run(
        "prepare",
        "--output-dir",
        str(tmp_path / "missing"),
        "--authorization",
        str(tmp_path / "does-not-exist.json"),
    )
    authorization_path = tmp_path / "authorization.json"
    _write_authorization(
        authorization_path,
        authorized_arm_ids=["LHA-001-baseline"],
        independent_cockpit_sessions=False,
    )
    incomplete = _run(
        "prepare",
        "--output-dir",
        str(tmp_path / "incomplete"),
        "--authorization",
        str(authorization_path),
    )
    expired_path = tmp_path / "expired.json"
    _write_authorization(
        expired_path,
        authorized_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-02T00:00:00Z",
    )
    expired = _run(
        "prepare",
        "--output-dir",
        str(tmp_path / "expired"),
        "--authorization",
        str(expired_path),
    )

    assert missing.returncode == 2
    assert incomplete.returncode == 2
    assert expired.returncode == 2
    errors = "\n".join(json.loads(incomplete.stdout)["errors"])
    assert "each of the 16 frozen arm IDs" in errors
    assert "independent Cockpit sessions" in errors
    assert "authorization receipt is expired" in "\n".join(
        json.loads(expired.stdout)["errors"]
    )


def test_evaluator_proceeds_on_quality_safe_strict_runtime_improvement_with_null_tokens(
    tmp_path: Path,
) -> None:
    records_dir = tmp_path / "records"
    _write_records(records_dir, _records())

    first = _run("evaluate", "--results-dir", str(records_dir))
    second = _run("evaluate", "--results-dir", str(records_dir))

    assert first.returncode == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["status"] == "evaluated"
    assert payload["record_integrity"]["denominator"] == 16
    assert payload["recommendation"]["option"] == "proceed"
    assert payload["recommendation"]["strict_runtime_cost_improvements"] == [
        "tool_command_calls"
    ]
    assert payload["token_claims"] == {
        "input_tokens": False,
        "output_tokens": False,
        "null_means_unavailable_not_zero": True,
    }
    assert payload["cost_metrics"]["input_tokens"]["observed_pairs"] == 0
    assert payload["cost_metrics"]["loaded_skill_bytes"]["strict_improvement"] is True


def test_skill_byte_improvement_alone_never_proceeds(tmp_path: Path) -> None:
    records_dir = tmp_path / "records"
    _write_records(records_dir, _records(runtime_improvement=False))

    result = _run("evaluate", "--results-dir", str(records_dir))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["recommendation"]["option"] == "modify"
    assert payload["recommendation"]["strict_runtime_cost_improvements"] == []
    assert "no_strict_fully_observed_runtime_cost_improvement" in payload[
        "recommendation"
    ]["reason_codes"]


def test_failed_and_safe_stopped_records_remain_in_denominator(tmp_path: Path) -> None:
    records = _records()
    records[0]["outcome"] = "safe_stopped"
    records[0]["safe_stop_observed"] = True
    records[1]["outcome"] = "failed"
    records[1]["acceptance_success"] = False
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run("evaluate", "--results-dir", str(records_dir))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["record_integrity"]["valid_records"] == 16
    assert payload["outcomes"]["failed"] == 1
    assert payload["outcomes"]["safe_stopped"] == 1
    assert payload["quality_metrics"]["acceptance_success"]["observed_pairs"] == 8
    assert payload["recommendation"]["option"] == "modify"


def test_duplicate_missing_mutated_and_contaminated_records_fail_closed(
    tmp_path: Path,
) -> None:
    records = _records()
    records.pop()
    duplicate = dict(records[0])
    duplicate["session_ref"] = "cockpit:test-fixture:duplicate"
    records.append(duplicate)
    records[2]["commit_full"] = "0" * 40
    records[3]["contaminated"] = True
    records[3]["outcome"] = "contaminated"
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run("evaluate", "--results-dir", str(records_dir))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert payload["record_integrity"]["denominator"] == 16
    assert payload["recommendation"]["option"] == "stop"
    errors = "\n".join(payload["errors"])
    assert "duplicate arm_id" in errors
    assert "missing arm record" in errors
    assert "commit_full mutated" in errors
    assert "contaminated result rejected fail-closed" in errors


def test_exact_schema_and_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    records_dir = tmp_path / "records"
    _write_records(records_dir, _records())
    first_path = sorted(records_dir.glob("*.json"))[0]
    first_path.write_text('{"arm_id":"one","arm_id":"two"}\n', encoding="utf-8")
    second_path = sorted(records_dir.glob("*.json"))[1]
    second = json.loads(second_path.read_text())
    second["unexpected"] = True
    second_path.write_text(json.dumps(second) + "\n", encoding="utf-8")

    result = _run("evaluate", "--results-dir", str(records_dir))

    assert result.returncode == 2
    errors = "\n".join(json.loads(result.stdout)["errors"])
    assert "duplicate JSON key: arm_id" in errors
    assert "unexpected fields: unexpected" in errors


def test_critical_gate_violation_stops_even_with_runtime_improvement(tmp_path: Path) -> None:
    records = _records()
    treatment = next(record for record in records if record["arm_id"] == "LHA-007-treatment")
    treatment["critical_gate_violation"] = True
    treatment["human_gate_integrity"] = False
    treatment["acceptance_success"] = False
    treatment["outcome"] = "failed"
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run("evaluate", "--results-dir", str(records_dir))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["safety_metrics"]["critical_gate_violations"] == 1
    assert payload["recommendation"]["option"] == "stop"
    assert payload["recommendation"]["phase5_authorized"] is False


def test_partial_provider_tokens_block_only_token_claims(tmp_path: Path) -> None:
    records = _records()
    for record in records:
        record["input_tokens"] = 1000
        record["output_tokens"] = 100
    records[0]["input_tokens"] = None
    records[0]["output_tokens"] = None
    records_dir = tmp_path / "records"
    _write_records(records_dir, records)

    result = _run("evaluate", "--results-dir", str(records_dir))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["recommendation"]["option"] == "proceed"
    assert payload["token_claims"]["input_tokens"] is False
    assert payload["token_claims"]["output_tokens"] is False
    assert payload["cost_metrics"]["tool_command_calls"]["strict_improvement"] is True


def test_pair_must_report_the_same_nonempty_actual_model(tmp_path: Path) -> None:
    records = _records()
    treatment = next(record for record in records if record["arm_id"] == "LHA-004-treatment")
    treatment["actual_model"] = "gpt-5.7-different"
    records_dir = tmp_path / "mismatch"
    _write_records(records_dir, records)

    mismatch = _run("evaluate", "--results-dir", str(records_dir))

    assert mismatch.returncode == 2
    assert "paired actual_model mismatch" in "\n".join(
        json.loads(mismatch.stdout)["errors"]
    )

    records = _records()
    records[0]["actual_model"] = ""
    records_dir = tmp_path / "empty"
    _write_records(records_dir, records)
    empty = _run("evaluate", "--results-dir", str(records_dir))

    assert empty.returncode == 2
    assert "actual_model must be a nonempty string" in "\n".join(
        json.loads(empty.stdout)["errors"]
    )
