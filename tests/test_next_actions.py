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
HUMAN_DECISION_ACTION_KEYS = {
    "why_blocked",
    "options",
    "recommendation",
    "recommendation_reason",
    "related_evidence_paths",
    "receipt_paths",
}
HUMAN_DECISION_OPTION_KEYS = {"label", "command", "why_safe", "risk_if_run"}


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


def _add_done_feature(root: Path, capsys, index: int) -> None:
    feature_id = f"F-{index:04d}"
    story_id = f"US-{index:04d}"
    test_id = f"TC-{index:04d}"
    assert main([
        "--root", str(root), "feature", "add", "--name", f"Feature {index}",
        "--surface", f"surface:{index}",
    ]) == 0
    assert main([
        "--root", str(root), "story", "draft", "--feature", feature_id,
        "--actor", "operator", "--goal", f"complete feature {index}",
        "--expected-behavior", f"Feature {index} is verified",
    ]) == 0
    assert main(["--root", str(root), "story", "approve", story_id, "--summary", "reviewed"]) == 0
    assert main([
        "--root", str(root), "test", "plan", "--feature", feature_id, "--story", story_id,
        "--type", "acceptance", "--scenario", f"Feature {index} works", "--expected", "passing",
    ]) == 0
    capsys.readouterr()
    artifact = root / f"feature-{index}-result.txt"
    artifact.write_text("passed\n", encoding="utf-8")
    assert main([
        "--root", str(root), "evidence", "add", "--file", artifact.name,
        "--summary", f"Feature {index} acceptance", "--copy", "--json",
    ]) == 0
    evidence_id = str(_json_output(capsys)["evidence"]["id"])
    assert main([
        "--root", str(root), "test", "pass", test_id, "--summary", "passed",
        "--evidence-id", evidence_id,
    ]) == 0
    assert main([
        "--root", str(root), "feature", "status", feature_id, "--status", "done",
        "--summary", f"Feature {index} complete", "--evidence-id", evidence_id,
    ]) == 0


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


def test_next_routes_checkpoint_review_before_more_goal_continuation(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Improve UX"]) == 0
    for index in range(1, 6):
        _add_done_feature(tmp_path, capsys, index)
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "checkpoint_review"
    assert action["priority"] == 58
    assert action["requires_human"] is True
    assert action["safe_to_run"] is False
    assert action["run_policy"] == "human_decision"
    assert action["target"]["completed_features_since_checkpoint"] == 5
    assert action["target"]["checkpoint_recommended"] is True

    assert main([
        "--root",
        str(tmp_path),
        "checkpoint",
        "record",
        "--summary",
        "Reviewed checkpoint",
        "--evidence",
        "Reviewed validation, UX checklist, and commit boundary",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    resumed = _json_output(capsys)
    _assert_guided_action(resumed)
    assert resumed["type"] == "continue_goal"
    assert resumed["command"] == "pcl loop run feature_coverage --goal G-0001"


def test_next_routes_goal_linked_ready_task_before_goal_continuation(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Task routing"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Highest priority task",
        "--priority",
        "10",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0001",
        "ready",
        "--reason",
        "Ready for routing",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "work_on_task"
    assert action["command"] == "pcl context pack --task T-0001 --json"
    assert action["priority"] == 59
    assert action["blocking"] is False
    assert action["requires_human"] is False
    assert action["safe_to_run"] is True
    assert action["run_policy"] == "agent_safe"
    assert action["target"]["id"] == "T-0001"
    assert action["target"]["related_goal_id"] == "G-0001"
    assert "highest-priority ready task" in action["reason"]


def test_next_routes_checkpoint_review_before_ready_task(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Checkpoint beats tasks"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Ready task",
        "--priority",
        "10",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0001",
        "ready",
        "--reason",
        "Ready for routing",
    ]) == 0
    for index in range(1, 6):
        _add_done_feature(tmp_path, capsys, index)
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "checkpoint_review"
    assert action["priority"] == 58


def test_next_prefers_in_progress_task_over_ready_task(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Task routing"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Ready task",
        "--priority",
        "1",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0001",
        "ready",
        "--reason",
        "Ready for routing",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Started task",
        "--priority",
        "50",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0002",
        "in_progress",
        "--reason",
        "Already started",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "work_on_task"
    assert action["command"] == "pcl context pack --task T-0002 --json"
    assert action["target"]["status"] == "in_progress"
    assert "already in progress" in action["reason"]


def test_next_skips_dependency_blocked_task(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Task dependencies"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Blocked top task",
        "--priority",
        "1",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0001",
        "ready",
        "--reason",
        "Ready except dependency",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Unmet dependency",
        "--priority",
        "20",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Available task",
        "--priority",
        "10",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0003",
        "ready",
        "--reason",
        "No blockers",
    ]) == 0
    assert main(["--root", str(tmp_path), "task", "depend", "T-0001", "--on", "T-0002"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "work_on_task"
    assert action["command"] == "pcl context pack --task T-0003 --json"
    assert action["target"]["dependency_ids"] == []


def test_next_ignores_unlinked_task(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Task routing"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Unlinked task",
        "--priority",
        "1",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "status",
        "T-0001",
        "ready",
        "--reason",
        "Ready but unlinked",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    _assert_guided_action(action)
    assert action["type"] == "continue_goal"
    assert action["priority"] == 60
    assert action["command"] == "pcl loop run feature_coverage --goal G-0001"


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


def test_next_json_human_decision_includes_cockpit_options(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
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
    action = _json_output(capsys)

    _assert_guided_action(action)
    assert HUMAN_DECISION_ACTION_KEYS <= set(action)
    assert action["type"] == "resolve_decision"
    assert action["why_blocked"] == "A human decision is open and blocks safe continuation."
    assert action["recommendation"] == "Pick safest"
    assert action["recommendation_reason"] == action["reason"]
    assert action["related_evidence_paths"] == []
    assert action["receipt_paths"] == []
    assert [option["label"] for option in action["options"]] == [
        "Approve",
        "Reject",
        "Hold",
        "Request more evidence",
    ]
    assert all(set(option) == HUMAN_DECISION_OPTION_KEYS for option in action["options"])
    assert action["options"][1]["command"] == (
        "pcl decision resolve DEC-0001 --selected-option 'Reject recommended path' "
        "--reason '<why this should not proceed>'"
    )


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


def _human_gated_action(*, action_type="record_verification", blocking=True):
    from pcl.commands import build_next_action

    return build_next_action(
        action_type=action_type,
        command="pcl verification record --run WR-0001 --result approved --reason '<why>'",
        reason="All active workflow jobs are terminal, but no approved verification exists.",
        target={"id": "WR-0001"},
        priority=40,
        blocking=blocking,
        requires_human=True,
        safe_to_run=False,
        expected_after="An approved verification exists for the run.",
    )


def test_human_gate_action_includes_japanese_guidance() -> None:
    action = _human_gated_action()
    ja = action["human_guidance_ja"]
    assert set(ja) == {"why_blocked", "check", "next_options"}
    # blocking prefix + record_verification specific reason, in Japanese.
    assert ja["why_blocked"].startswith("通常のループ継続は待つべきです。")
    assert "検証" in ja["why_blocked"]
    assert isinstance(ja["check"], list) and ja["check"]
    assert any("証跡" in item for item in ja["check"])
    # next_options are Japanese labels mapped 1:1 from the English options order.
    assert ja["next_options"] == ["承認する", "却下する", "保留する", "追加の証跡を確認する"]
    # additive: the English fields are unchanged.
    assert isinstance(action["why_blocked"], str)
    assert [o["label"] for o in action["options"]] == [
        "Approve",
        "Reject",
        "Hold",
        "Request more evidence",
    ]


def test_human_gate_default_reason_when_action_type_unmapped() -> None:
    action = _human_gated_action(action_type="continue_goal", blocking=False)
    ja = action["human_guidance_ja"]
    assert not ja["why_blocked"].startswith("通常のループ継続は待つべきです。")
    assert "durable" in ja["why_blocked"]


def test_agent_safe_action_has_no_japanese_guidance() -> None:
    from pcl.commands import build_next_action

    action = build_next_action(
        action_type="continue_workflow",
        command="pcl jobs read J-0001",
        reason="A workflow run is already active and has queued or running jobs.",
        target={"id": "WR-0001"},
        priority=40,
        blocking=False,
        requires_human=False,
        safe_to_run=True,
        expected_after="The agent job prompt is reviewed.",
    )
    assert "human_guidance_ja" not in action
    assert action["run_policy"] == "agent_safe"
