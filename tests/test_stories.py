from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()


def _add_feature(root: Path, capsys, *, name: str = "Harness feature") -> str:
    assert main([
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        name,
        "--surface",
        "cli:pcl",
        "--json",
    ]) == 0
    return str(_json_output(capsys)["id"])


def _dashboard_data(root: Path) -> dict:
    return json.loads((root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))


def test_story_and_test_case_lifecycle_updates_dashboard(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_id = _add_feature(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "draft",
        "--feature",
        feature_id,
        "--actor",
        "coding agent",
        "--goal",
        "record coverage artifacts",
        "--benefit",
        "coverage can be reviewed from durable state",
        "--expected-behavior",
        "story and test state changes append events",
        "--json",
    ]) == 0
    story = _json_output(capsys)
    assert story["id"] == "US-0001"
    assert story["status"] == "draft"
    assert story["feature_id"] == feature_id

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "review",
        "US-0001",
        "--summary",
        "Ready for approval",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "review"

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "approve",
        "US-0001",
        "--summary",
        "Matches the feature behavior",
        "--json",
    ]) == 0
    approved = _json_output(capsys)
    assert approved["status"] == "approved"
    assert approved["feature_status"] == "specified"

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "read",
        "US-0001",
        "--json",
    ]) == 0
    read_story = _json_output(capsys)
    assert read_story["story"]["status"] == "approved"

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "plan",
        "--feature",
        feature_id,
        "--story",
        "US-0001",
        "--type",
        "unit",
        "--scenario",
        "CLI records a test case",
        "--expected",
        "The test case appears in durable state",
        "--json",
    ]) == 0
    planned = _json_output(capsys)
    assert planned["id"] == "TC-0001"
    assert planned["story_id"] == "US-0001"
    assert planned["status"] == "planned"
    assert planned["feature_status"] == "needs_test"

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "create",
        "--title",
        "Coverage run",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "CLI lifecycle test passed",
        "--evidence",
        "pytest tests/test_stories.py::test_story_and_test_case_lifecycle_updates_dashboard passed",
        "--run",
        "WR-0001",
        "--json",
    ]) == 0
    passed = _json_output(capsys)
    assert passed["status"] == "passing"
    assert passed["workflow_run_id"] == "WR-0001"
    assert passed["evidence_id"] == "E-0001"
    assert passed["feature_status"] == "passing"

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "read",
        "TC-0001",
        "--json",
    ]) == 0
    read_test = _json_output(capsys)
    assert read_test["test_case"]["last_run_id"] == "WR-0001"
    assert read_test["test_case"]["evidence_id"] == "E-0001"

    assert main(["--root", str(tmp_path), "story", "list", "--feature", feature_id, "--json"]) == 0
    listed_stories = _json_output(capsys)
    assert [story["id"] for story in listed_stories["stories"]] == ["US-0001"]

    assert main(["--root", str(tmp_path), "test", "list", "--story", "US-0001", "--json"]) == 0
    listed_tests = _json_output(capsys)
    assert [test_case["id"] for test_case in listed_tests["test_cases"]] == ["TC-0001"]

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = _dashboard_data(tmp_path)
    assert data["counts"]["user_stories"] == 1
    assert data["counts"]["test_cases"] == 1
    assert data["user_stories"][0]["id"] == "US-0001"
    assert data["test_cases"][0]["id"] == "TC-0001"
    assert data["features"][0]["status"] == "passing"

    html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
    assert "Story Coverage" in html
    assert "Test Coverage" in html
    assert "US-0001" in html
    assert "TC-0001" in html

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "user_story_drafted" in events
    assert "user_story_reviewed" in events
    assert "user_story_approved" in events
    assert "test_case_planned" in events
    assert "test_case_passed" in events


def test_story_and_test_case_invalid_inputs_return_typed_json(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_id = _add_feature(tmp_path, capsys, name="Feature one")
    other_feature_id = _add_feature(tmp_path, capsys, name="Feature two")

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "draft",
        "--feature",
        feature_id,
        "--actor",
        "operator",
        "--goal",
        "track behavior",
        "--expected-behavior",
        "story exists",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "plan",
        "--feature",
        other_feature_id,
        "--story",
        "US-0001",
        "--type",
        "unit",
        "--scenario",
        "Linked story belongs to another feature",
        "--expected",
        "The link is rejected",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be linked to feature" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "plan",
        "--feature",
        feature_id,
        "--type",
        "load",
        "--scenario",
        "Unsupported type",
        "--expected",
        "Typed error",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Invalid test case type" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "list",
        "--status",
        "done",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Invalid story status" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "list",
        "--status",
        "done",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Invalid test case status" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "plan",
        "--feature",
        feature_id,
        "--type",
        "unit",
        "--scenario",
        "Evidence is required before pass",
        "--expected",
        "Pass rejects missing evidence",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "No evidence",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "evidence is required" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Passed once",
        "--evidence",
        "pytest passed",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Passed twice",
        "--evidence",
        "pytest passed again",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "already passing" in payload["error"]["message"]


def test_story_waive_and_test_case_failure_states(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_id = _add_feature(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "draft",
        "--feature",
        feature_id,
        "--actor",
        "operator",
        "--goal",
        "waive obsolete behavior",
        "--expected-behavior",
        "waiver is recorded",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "story",
        "waive",
        "US-0001",
        "--reason",
        "No longer needed",
        "--json",
    ]) == 0
    waived_story = _json_output(capsys)
    assert waived_story["status"] == "waived"
    assert waived_story["reason"] == "No longer needed"

    for index, transition in enumerate(("fail", "block", "missing", "waive"), start=1):
        assert main([
            "--root",
            str(tmp_path),
            "test",
            "plan",
            "--feature",
            feature_id,
            "--type",
            "manual",
            "--scenario",
            f"Scenario {transition}",
            "--expected",
            f"Expected {transition}",
        ]) == 0
        capsys.readouterr()
        test_case_id = f"TC-{index:04d}"
        if transition == "fail":
            command = [
                "--root",
                str(tmp_path),
                "test",
                "fail",
                test_case_id,
                "--summary",
                "Observed failure",
                "--evidence",
                "pytest failed",
                "--json",
            ]
            expected_status = "failing"
        elif transition == "block":
            command = [
                "--root",
                str(tmp_path),
                "test",
                "block",
                test_case_id,
                "--summary",
                "Blocked by missing fixture",
                "--json",
            ]
            expected_status = "blocked"
        elif transition == "missing":
            command = [
                "--root",
                str(tmp_path),
                "test",
                "missing",
                test_case_id,
                "--summary",
                "Implementation is not covered",
                "--json",
            ]
            expected_status = "missing"
        else:
            command = [
                "--root",
                str(tmp_path),
                "test",
                "waive",
                test_case_id,
                "--reason",
                "Out of scope",
                "--json",
            ]
            expected_status = "waived"

        assert main(command) == 0
        result = _json_output(capsys)
        assert result["status"] == expected_status

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = _dashboard_data(tmp_path)
    statuses = {test_case["id"]: test_case["status"] for test_case in data["test_cases"]}
    assert statuses == {
        "TC-0001": "failing",
        "TC-0002": "blocked",
        "TC-0003": "missing",
        "TC-0004": "waived",
    }
    assert data["features"][0]["status"] == "needs_fix"

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "user_story_waived" in events
    assert "test_case_failed" in events
    assert "test_case_blocked" in events
    assert "test_case_marked_missing" in events
    assert "test_case_waived" in events
