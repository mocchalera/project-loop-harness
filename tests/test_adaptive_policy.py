from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcl.adaptive_policy import (
    AdaptivePolicyError,
    default_policy,
    load_policy,
    policy_resolution_schema,
    render_policy_explanation,
    resolve_policy,
    validate_policy,
)
from pcl.cli import main
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.start import start_work


def _recommendation(
    *,
    profile: str = "direct",
    risk: str = "R0",
    reasons: list[str] | None = None,
) -> dict:
    return {
        "contract_version": "route-recommendation/v1",
        "policy_version": "adaptive-entry-route/v1",
        "target": {"type": "task", "id": "T-0001"},
        "input_digest": "sha256:" + "1" * 64,
        "profile": profile,
        "risk_level": risk,
        "signals": {"model_self_assessment_used": False},
        "reason_codes": reasons or ["clear_acceptance"],
        "work_brief_ref": None,
        "work_brief_sha256": None,
    }


def _project(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "project"
    root.mkdir()
    paths = resolve_paths(root)
    init_project(paths)
    started = start_work(paths, intent="Explain adaptive policy")
    return root, str(started["result"]["created_ids"]["task"])


def _counts(root: Path) -> tuple[int, int, int, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("evidence", "events", "outbox_records", "evidence_links")
        )
    finally:
        conn.close()


def test_default_policy_and_resolution_schema_are_packaged() -> None:
    policy = default_policy()
    schema = policy_resolution_schema()

    assert policy["contract_version"] == "adaptive-policy/v1"
    assert validate_policy(policy) == []
    assert schema["$id"].endswith("adaptive-policy-resolution-v1.schema.json")


def test_direct_resolution_is_deterministic_with_field_sources() -> None:
    recommendation = _recommendation()

    first = resolve_policy(recommendation)
    second = resolve_policy(recommendation)

    assert first == second
    assert first["profile"] == "direct"
    assert first["axes"]["planning_depth"] == "light"
    assert first["sources"]["planning_depth"] == "profile:direct"
    assert first["sources"]["verification_depth"] == "defaults"
    assert first["policy_sha256"].startswith("sha256:")
    assert "planning_depth: light (profile:direct)" in render_policy_explanation(first)


def test_assure_resolution_applies_non_overridable_risk_floor() -> None:
    recommendation = _recommendation(
        profile="assure",
        risk="R3",
        reasons=["auth_or_permission_change", "clear_acceptance"],
    )
    policy = default_policy()
    policy["profile_rules"]["assure"]["verification_depth"] = "basic"

    resolution = resolve_policy(recommendation, policy=policy)

    assert resolution["axes"]["verification_depth"] == "independent"
    assert resolution["axes"]["execution_chunk_size"] == "small"
    assert resolution["axes"]["checkpoint_frequency"] == "high"
    assert resolution["sources"]["verification_depth"] == "risk_floor:R3"


def test_project_rule_records_per_axis_source() -> None:
    policy = default_policy()
    policy["rules"] = [
        {
            "id": "direct-context-budget",
            "when": {"profiles": ["direct"]},
            "set": {"context_budget_bytes": 12000},
        }
    ]

    resolution = resolve_policy(_recommendation(), policy=policy)

    assert resolution["axes"]["context_budget_bytes"] == 12000
    assert resolution["sources"]["context_budget_bytes"] == "rule:direct-context-budget"
    assert resolution["matched_rule_ids"] == ["direct-context-budget"]


def test_conflicting_matched_rules_fail_closed() -> None:
    policy = default_policy()
    policy["rules"] = [
        {
            "id": "first",
            "when": {"profiles": ["direct"]},
            "set": {"context_budget_bytes": 12000},
        },
        {
            "id": "second",
            "when": {"reason_codes_any": ["clear_acceptance"]},
            "set": {"context_budget_bytes": 16000},
        },
    ]

    with pytest.raises(AdaptivePolicyError) as exc_info:
        resolve_policy(_recommendation(), policy=policy)

    assert exc_info.value.code == "adaptive_policy_rule_conflict"
    assert exc_info.value.details["conflicts"] == {
        "context_budget_bytes": ["first", "second"]
    }


def test_unknown_policy_fields_and_weak_risk_floor_are_rejected() -> None:
    unknown = default_policy()
    unknown["surprise"] = True
    weak = default_policy()
    weak["risk_floors"]["R3"]["verification_depth"] = "standard"

    assert "$.surprise: unknown field" in validate_policy(unknown)
    assert any("must not be weaker than independent" in item for item in validate_policy(weak))


def test_policy_file_validation_is_typed(tmp_path: Path) -> None:
    policy = default_policy()
    policy["rules"] = [
        {
            "id": "bad-axis",
            "when": {"profiles": ["direct"]},
            "set": {"unknown_axis": "value"},
        }
    ]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(AdaptivePolicyError) as exc_info:
        load_policy(path)

    assert exc_info.value.code == "adaptive_policy_invalid"
    assert any("unknown policy axis" in item for item in exc_info.value.details["errors"])


def test_policy_resolve_and_explain_cli_are_read_only(tmp_path: Path, capsys) -> None:
    root, task_id = _project(tmp_path)
    before = _counts(root)
    base_args = ["--root", str(root), "policy"]

    assert main([*base_args, "resolve", "--target", f"task:{task_id}", "--json"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["resolution"]["profile"] == "discover"
    assert main([*base_args, "explain", "--target", f"task:{task_id}"]) == 0
    explanation = capsys.readouterr().out

    assert "Resolved axes:" in explanation
    assert "risk=R1" in explanation
    assert _counts(root) == before
