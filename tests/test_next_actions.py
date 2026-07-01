from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect
from pcl.events import append_event


COMMAND_ONLY_WORKFLOW = """\
id: validate_auto
name: "Validate Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Run validation automatically.
  completion: []
agents: {}
steps:
  - id: validate
    command: pcl validate
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""


FAILING_PROJECT_COMMAND_WORKFLOW = """\
id: failing_test_auto
name: "Failing Test Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Run a failing project command.
  completion: []
agents: {}
steps:
  - id: test
    command: project.commands.test
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""


GUIDED_ACTION_KEYS = {
    "type",
    "command",
    "reason",
    "target",
    "priority",
    "blocking",
    "requires_human",
    "safe_to_run",
    "run_policy",
    "human_guidance",
    "expected_after",
}


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _assert_guided_action(action: dict) -> None:
    assert GUIDED_ACTION_KEYS.issubset(action)
    assert isinstance(action["type"], str)
    assert isinstance(action["command"], str)
    assert isinstance(action["reason"], str)
    assert isinstance(action["priority"], int)
    assert isinstance(action["blocking"], bool)
    assert isinstance(action["requires_human"], bool)
    assert isinstance(action["safe_to_run"], bool)
    assert isinstance(action["run_policy"], str)
    assert isinstance(action["human_guidance"], str)
    assert isinstance(action["expected_after"], str)


def _approve_workflow(tmp_path: Path, capsys, workflow_text: str) -> None:
    source = tmp_path / "workflow.yaml"
    source.write_text(workflow_text, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "workflow.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approve for next-action test",
    ]) == 0
    capsys.readouterr()


def test_next_json_returns_guided_schema_for_create_goal(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "create_goal"
    assert action["priority"] == 70
    assert action["blocking"] is False
    assert action["requires_human"] is True
    assert action["safe_to_run"] is False
    assert action["run_policy"] == "human_decision"
    assert "human should choose" in action["human_guidance"]
    assert "open goal exists" in action["expected_after"]


def test_next_routes_uncovered_feature_before_generic_goal(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "Migrations",
        "--surface",
        "cli:pcl migrate",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "cover_feature"
    assert action["command"] == "pcl goal create --title 'Cover feature F-0001'"
    assert action["priority"] == 65
    assert action["blocking"] is False
    assert action["requires_human"] is True
    assert action["safe_to_run"] is False
    assert action["target"]["id"] == "F-0001"
    assert action["target"]["status"] == "discovered"
    assert "tracked feature still needs coverage" in action["reason"]


def test_next_strict_validation_failure_uses_guided_schema_and_first_priority(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "regression_loop", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--strict", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "resolve_validation_errors"
    assert action["priority"] == 1
    assert action["blocking"] is True
    assert action["requires_human"] is True
    assert action["safe_to_run"] is True
    assert action["command"] == "pcl report validation --strict"


def test_next_priority_order_for_human_and_workflow_actions(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "escalation", "open", "--severity", "high", "--question", "Needs human"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    escalation = _json_output(capsys)
    _assert_guided_action(escalation)
    assert escalation["type"] == "resolve_escalation"
    assert escalation["priority"] == 10
    assert escalation["blocking"] is True

    assert main(["--root", str(tmp_path), "escalation", "cancel", "ESC-0001", "--summary", "Not needed"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Choose path",
        "--recommendation",
        "Pick safest",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    decision = _json_output(capsys)
    _assert_guided_action(decision)
    assert decision["type"] == "resolve_decision"
    assert decision["priority"] == 20
    assert decision["requires_human"] is True

    assert main(["--root", str(tmp_path), "decision", "waive", "DEC-0001", "--reason", "No longer needed"]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    workflow = _json_output(capsys)
    _assert_guided_action(workflow)
    assert workflow["type"] == "continue_workflow"
    assert workflow["priority"] == 40
    assert workflow["safe_to_run"] is True


def test_next_routes_unfinished_executor_run_to_resume(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, COMMAND_ONLY_WORKFLOW)
    assert main(["--root", str(tmp_path), "loop", "run", "validate_auto", "--json"]) == 0
    assert _json_output(capsys)["workflow_run"]["id"] == "WR-0001"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        append_event(
            conn=conn,
            events_path=tmp_path / ".project-loop" / "events.jsonl",
            event_type="workflow_execution_started",
            entity_type="workflow_run",
            entity_id="WR-0001",
            payload={"contract_version": "workflow-executor/v1", "workflow_id": "validate_auto"},
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "resume_workflow_execution"
    assert action["command"] == "pcl loop execute validate_auto --resume WR-0001"
    assert action["priority"] == 35
    assert action["blocking"] is True


def test_next_routes_unretried_failed_executor_run_to_retry(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("test: \"\"", "test: \"python -m pytest missing_test_file.py\""),
        encoding="utf-8",
    )
    _approve_workflow(tmp_path, capsys, FAILING_PROJECT_COMMAND_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--json"]) == 1
    failed = _json_output(capsys)
    assert failed["workflow_run_id"] == "WR-0001"
    assert failed["status"] == "failed"

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "retry_workflow_execution"
    assert action["command"] == "pcl loop execute failing_test_auto --retry WR-0001"
    assert action["target"]["evidence_id"] == "E-0001"
    assert action["priority"] == 45


def test_next_explain_prints_guided_fields(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--explain"]) == 0
    output = capsys.readouterr().out
    assert "Next action: create_goal" in output
    assert "Priority: 70" in output
    assert "Blocking: no" in output
    assert "Requires human: yes" in output
    assert "Safe to run: no" in output
    assert "Run policy: human_decision" in output
    assert "Human guidance:" in output
    assert "Expected after:" in output


def test_dashboard_next_action_block_renders_guided_fields(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)

    data = json.loads((tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    _assert_guided_action(data["next_action"])
    assert data["next_action"]["type"] == "continue_workflow"
    assert data["next_action"]["priority"] == 40

    html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
    assert "priority" in html
    assert "blocking" in html
    assert "requires_human" in html
    assert "safe_to_run" in html
    assert "run_policy" in html
    assert "human_guidance" in html
    assert "expected_after" in html
