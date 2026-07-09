from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect
from pcl.workflow_yaml import parse_workflow_yaml


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_parse_workflow_yaml_subset() -> None:
    parsed = parse_workflow_yaml(
        """
id: demo
name: "Demo Workflow"
type: closed_loop
version: "0.1.0"
agents:
  mapper:
    mode: read_only
    purpose: Map surfaces.
steps:
  - id: map
    agent: mapper
    input:
      - one
      - two
  - id: decide
    rules:
      - if: result == approved
        then: close
      - else: retry
budget:
  max_iterations: 2
stop_conditions:
  - done
"""
    )

    assert parsed["id"] == "demo"
    assert parsed["agents"]["mapper"]["mode"] == "read_only"
    assert parsed["steps"][0]["input"] == ["one", "two"]
    assert parsed["steps"][1]["rules"][0]["if"] == "result == approved"
    assert parsed["steps"][1]["rules"][1]["else"] == "retry"


def test_parse_workflow_yaml_accepts_plain_rule_comparisons() -> None:
    parsed = parse_workflow_yaml(
        """
id: demo
name: Demo Workflow
type: closed_loop
version: "0.1.0"
goal:
  description: Demo
agents: {}
steps:
  - id: decide
    rules:
      - if: loop.iteration >= 2
        then: escalate_to_human
      - if: retry.count <= 1
        then: retry
budget:
  max_iterations: 2
stop_conditions:
  - max_iterations_reached
"""
    )

    assert parsed["steps"][0]["rules"] == [
        {"if": "loop.iteration >= 2", "then": "escalate_to_human"},
        {"if": "retry.count <= 1", "then": "retry"},
    ]


def test_loop_run_creates_workflow_run_jobs_and_prompts(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
        "--json",
    ]) == 0
    result = _json_output(capsys)

    assert result["workflow_run"]["id"] == "WR-0001"
    assert result["workflow_run"]["workflow_id"] == "feature_coverage"
    assert [job["role"] for job in result["jobs"]] == ["mapper", "story_writer", "test_designer"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
        job_count = conn.execute("SELECT COUNT(*) AS n FROM agent_jobs").fetchone()["n"]
        assert run_count == 1
        assert job_count == 3
    finally:
        conn.close()

    for job in result["jobs"]:
        prompt_path = tmp_path / job["prompt_path"]
        assert prompt_path.exists()
        prompt = prompt_path.read_text(encoding="utf-8")
        assert f"# Agent Job {job['id']}" in prompt
        assert "Do not edit `.project-loop/project.db` directly." in prompt
        assert "Do not read or parse generated dashboard HTML as project state." in prompt
        assert "dashboard-data.json" in prompt
        assert (
            "Valid `pcl test plan --type` values: acceptance, e2e, integration, manual, smoke, unit."
            in prompt
        )
        assert (
            "Valid `pcl feature status --status` values: discovered, done, needs_fix, "
            "needs_test, passing, specified, waived."
            in prompt
        )

    test_designer_prompt = (tmp_path / result["jobs"][2]["prompt_path"]).read_text(encoding="utf-8")
    assert "Propose unit, integration, e2e, manual, smoke, or acceptance tests" in test_designer_prompt

    assert main(["--root", str(tmp_path), "jobs", "list", "--json"]) == 0
    jobs = _json_output(capsys)
    assert len(jobs["jobs"]) == 3
    assert jobs["jobs"][0]["id"] == "J-0001"

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    job = _json_output(capsys)["job"]
    assert job["id"] == "J-0001"
    assert "Role: mapper" in job["prompt"]

    assert main(["--root", str(tmp_path), "render"]) == 0
    dashboard = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    assert "WR-0001" in dashboard
    assert "J-0001" in dashboard


def test_jobs_list_filters_by_run_and_status(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0004",
        "--summary",
        "Mapper done",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "jobs", "list", "--run", "WR-0002", "--json"]) == 0
    run_jobs = _json_output(capsys)["jobs"]
    assert [job["id"] for job in run_jobs] == ["J-0004", "J-0005", "J-0006"]
    assert {job["workflow_run_id"] for job in run_jobs} == {"WR-0002"}

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "list",
        "--run",
        "WR-0002",
        "--status",
        "queued",
        "--json",
    ]) == 0
    queued_jobs = _json_output(capsys)["jobs"]
    assert [job["id"] for job in queued_jobs] == ["J-0005", "J-0006"]
    assert {job["status"] for job in queued_jobs} == {"queued"}

    assert main(["--root", str(tmp_path), "jobs", "list", "--run", "WR-9999", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"] == {"workflow_run_id": "WR-9999"}


def test_loop_run_accepts_legacy_unquoted_defect_repair_rule_expression(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    workflow_path = tmp_path / ".project-loop" / "workflows" / "defect_repair.yaml"
    workflow_path.write_text(
        workflow_path.read_text(encoding="utf-8").replace(
            'if: "loop.iteration >= 2"',
            "if: loop.iteration >= 2",
        ),
        encoding="utf-8",
    )
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "Repairable feature",
        "--surface",
        "cli:pcl",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "medium",
        "--expected",
        "Workflow starts",
        "--actual",
        "Parser rejects rule expression",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "defect_repair",
        "--defect",
        "D-0001",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["workflow_run"]["id"] == "WR-0001"
    assert result["workflow_run"]["defect_id"] == "D-0001"
    assert [job["role"] for job in result["jobs"]] == ["explorer", "implementer", "verifier"]


def test_loop_run_rejects_unknown_workflow(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "loop", "run", "missing", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Workflow template does not exist" in payload["error"]["message"]


def test_loop_run_rejects_unknown_goal(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-9999",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Goal does not exist" in payload["error"]["message"]


def test_jobs_commands_require_init(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "jobs", "list", "--json"]) == 3
    assert _json_output(capsys)["error"]["code"] == "not_initialized"


def _add_feature(tmp_path: Path, name: str, capsys) -> None:
    assert main([
        "--root", str(tmp_path), "feature", "add",
        "--name", name, "--surface", "surface", "--description", "desc",
    ]) == 0
    capsys.readouterr()


def _cover_feature(tmp_path: Path, feature_id: str, capsys) -> None:
    assert main([
        "--root", str(tmp_path), "feature", "status", feature_id,
        "--status", "passing", "--summary", "covered", "--evidence", "test output",
    ]) == 0
    capsys.readouterr()


def test_feature_coverage_noop_when_all_features_covered(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    _add_feature(tmp_path, "Login", capsys)
    _cover_feature(tmp_path, "F-0001", capsys)

    assert main([
        "--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001", "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["no_op"] is True
    assert result["reason"] == "feature_coverage_already_covered"
    assert result["workflow_run"] is None
    assert result["jobs"] == []
    assert result["covered_feature_count"] == 1
    assert result["feature_count"] == 1

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM agent_jobs").fetchone()["n"] == 0
    finally:
        conn.close()
    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "workflow_run_created" not in events

    # Idempotent: still a no-op on a second run.
    assert main([
        "--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001", "--json",
    ]) == 0
    assert _json_output(capsys)["no_op"] is True


def test_feature_coverage_runs_when_a_feature_is_uncovered(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    _add_feature(tmp_path, "Login", capsys)
    _add_feature(tmp_path, "Signup", capsys)
    _cover_feature(tmp_path, "F-0001", capsys)  # F-0002 stays 'discovered'

    assert main([
        "--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001", "--json",
    ]) == 0
    result = _json_output(capsys)
    assert "no_op" not in result
    # The no-op did not consume WR-0001.
    assert result["workflow_run"]["id"] == "WR-0001"
    assert result["jobs"]


def test_feature_coverage_runs_when_no_features_exist(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()

    assert main([
        "--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001", "--json",
    ]) == 0
    result = _json_output(capsys)
    assert "no_op" not in result
    assert result["workflow_run"]["workflow_id"] == "feature_coverage"


def test_non_feature_coverage_workflow_runs_despite_covered_features(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    _add_feature(tmp_path, "Login", capsys)
    _cover_feature(tmp_path, "F-0001", capsys)

    assert main([
        "--root", str(tmp_path), "loop", "run", "executor_smoke", "--goal", "G-0001", "--json",
    ]) == 0
    result = _json_output(capsys)
    assert "no_op" not in result
    assert result["workflow_run"]["workflow_id"] == "executor_smoke"
