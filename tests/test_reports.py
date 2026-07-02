from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _valid_rubric() -> dict:
    return {
        "contract_version": "rubric/v1",
        "acceptance_criteria": [
            {"criterion": "Acceptance one", "met": "yes", "evidence_id": None},
            {"criterion": "Acceptance two", "met": "unknown", "evidence_id": None},
        ],
        "regression_risk": {"level": "medium", "notes": "One manual edge remains"},
        "test_evidence": [],
        "security_ux_checks": [{"check": "No secrets emitted", "result": "pass", "notes": None}],
        "confidence_score": 0.75,
        "evidence_completeness": "partial",
    }


def _build_closed_goal(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(root),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    assert main([
        "--root",
        str(root),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "pytest passed",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Workflow complete",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Goal complete",
        "--verification",
        "V-0001",
    ]) == 0
    capsys.readouterr()


def _build_closed_goal_with_coverage_context(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(root),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    assert main([
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        "Coverage reports",
        "--surface",
        "cli:pcl report",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "story",
        "draft",
        "--feature",
        "F-0001",
        "--actor",
        "operator",
        "--goal",
        "review coverage reports",
        "--expected-behavior",
        "reports include linked coverage state",
    ]) == 0
    assert main(["--root", str(root), "story", "review", "US-0001", "--summary", "Ready"]) == 0
    assert main(["--root", str(root), "story", "approve", "US-0001", "--summary", "Approved"]) == 0
    assert main([
        "--root",
        str(root),
        "test",
        "plan",
        "--feature",
        "F-0001",
        "--story",
        "US-0001",
        "--type",
        "unit",
        "--scenario",
        "Report includes coverage context",
        "--expected",
        "Feature, story, test case, and evidence appear in the report",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Coverage report context passed",
        "--evidence",
        "pytest tests/test_reports.py::test_report_goal_and_run_include_coverage_context passed",
        "--run",
        "WR-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "coverage report verified",
    ]) == 0
    assert main(["--root", str(root), "loop", "complete", "WR-0001", "--summary", "Workflow complete"]) == 0
    assert main([
        "--root",
        str(root),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Goal complete",
        "--verification",
        "V-0001",
    ]) == 0
    capsys.readouterr()


def _build_closed_defect(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Error message",
        "--actual",
        "Blank page",
    ]) == 0
    assert main(["--root", str(root), "defect", "triage", "D-0001", "--summary", "Triaged"]) == 0
    assert main(["--root", str(root), "defect", "start", "D-0001", "--summary", "Started"]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "fix",
        "D-0001",
        "--summary",
        "Fixed",
        "--evidence",
        "commit abc123 and pytest passed",
    ]) == 0
    assert main(["--root", str(root), "loop", "run", "defect_repair", "--defect", "D-0001"]) == 0
    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(root),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    assert main([
        "--root",
        str(root),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "defect repair verified",
    ]) == 0
    assert main(["--root", str(root), "loop", "complete", "WR-0001", "--summary", "Repair complete"]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "verify",
        "D-0001",
        "--summary",
        "Verification approved",
        "--verification",
        "V-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "close",
        "D-0001",
        "--summary",
        "Closed",
        "--evidence",
        "V-0001 approved",
    ]) == 0
    capsys.readouterr()


def test_report_goal_and_run_are_deterministic_and_include_evidence(tmp_path: Path, capsys) -> None:
    _build_closed_goal(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    goal = _json_output(capsys)
    goal_path = Path(goal["path"])
    first_goal = goal_path.read_text(encoding="utf-8")
    assert goal["kind"] == "goal"
    assert goal["report"]["goal"]["status"] == "closed"
    assert "# Goal Report: G-0001" in first_goal
    assert "Workflow Runs" in first_goal
    assert "V-0001" in first_goal
    assert "goal_closed" in first_goal

    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    _json_output(capsys)
    assert goal_path.read_text(encoding="utf-8") == first_goal

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run = _json_output(capsys)
    run_path = Path(run["path"])
    run_report = run_path.read_text(encoding="utf-8")
    assert run["kind"] == "run"
    assert run["report"]["workflow_run"]["status"] == "passed"
    assert "# Workflow Run Report: WR-0001" in run_report
    assert "J-0001" in run_report
    assert "verification_recorded" in run_report

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = json.loads((tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    report_paths = [row["path"] for row in data["reports"]]
    assert ".project-loop/reports/goal-G-0001.md" in report_paths
    assert ".project-loop/reports/run-WR-0001.md" in report_paths


def test_report_run_renders_compact_rubric_v1_summary(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--rubric-json",
        json.dumps(_valid_rubric()),
        "--reason",
        "Structured rubric reviewed",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run = _json_output(capsys)
    report = Path(run["path"]).read_text(encoding="utf-8")

    assert "## Verification Rubrics" in report
    assert "criteria_yes" in report
    assert "| V-0001 | 1 | 0 | 1 | 2 | medium | 0.75 | partial |" in report


def test_report_includes_all_repeated_agent_output_ingests(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
    ]) == 0

    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# First result\n\n"
        "## Findings\n\n"
        "- Initial agent output.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
    ]) == 0
    output_path.write_text(
        "# Second result\n\n"
        "## Findings\n\n"
        "- Updated agent output.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run = _json_output(capsys)
    run_evidence_ids = [row["id"] for row in run["report"]["evidence"]]
    assert run_evidence_ids == ["E-0001", "E-0002"]

    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    goal = _json_output(capsys)
    goal_evidence_ids = [row["id"] for row in goal["report"]["evidence"]]
    assert goal_evidence_ids == ["E-0001", "E-0002"]


def test_report_goal_and_run_include_coverage_context(tmp_path: Path, capsys) -> None:
    _build_closed_goal_with_coverage_context(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run = _json_output(capsys)
    run_report = Path(run["path"]).read_text(encoding="utf-8")
    assert [feature["id"] for feature in run["report"]["features"]] == ["F-0001"]
    assert [story["id"] for story in run["report"]["user_stories"]] == ["US-0001"]
    assert [test_case["id"] for test_case in run["report"]["test_cases"]] == ["TC-0001"]
    assert [evidence["id"] for evidence in run["report"]["evidence"]] == ["E-0001"]
    assert "## Features" in run_report
    assert "## User Stories" in run_report
    assert "## Test Cases" in run_report
    assert "Coverage reports" in run_report
    assert "US-0001" in run_report
    assert "TC-0001" in run_report
    assert "test_case_passed" in run_report
    assert "E-0001" in run_report

    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    goal = _json_output(capsys)
    goal_report = Path(goal["path"]).read_text(encoding="utf-8")
    assert [feature["id"] for feature in goal["report"]["features"]] == ["F-0001"]
    assert [story["id"] for story in goal["report"]["user_stories"]] == ["US-0001"]
    assert [test_case["id"] for test_case in goal["report"]["test_cases"]] == ["TC-0001"]
    assert [evidence["id"] for evidence in goal["report"]["evidence"]] == ["E-0001"]
    assert "## Features" in goal_report
    assert "## User Stories" in goal_report
    assert "## Test Cases" in goal_report
    assert "Coverage reports" in goal_report
    assert "test_case_passed" in goal_report


def test_report_feature_includes_coverage_context(tmp_path: Path, capsys) -> None:
    _build_closed_goal_with_coverage_context(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "report", "feature", "F-0001", "--json"]) == 0
    feature = _json_output(capsys)
    report = Path(feature["path"]).read_text(encoding="utf-8")

    assert feature["kind"] == "feature"
    assert feature["report"]["feature"]["id"] == "F-0001"
    assert [story["id"] for story in feature["report"]["user_stories"]] == ["US-0001"]
    assert [test_case["id"] for test_case in feature["report"]["test_cases"]] == ["TC-0001"]
    assert [run["id"] for run in feature["report"]["workflow_runs"]] == ["WR-0001"]
    assert [job["id"] for job in feature["report"]["agent_jobs"]] == ["J-0001", "J-0002", "J-0003"]
    assert [verification["id"] for verification in feature["report"]["verifications"]] == ["V-0001"]
    assert [evidence["id"] for evidence in feature["report"]["evidence"]] == ["E-0001"]
    assert "# Feature Report: F-0001" in report
    assert "## User Stories" in report
    assert "## Test Cases" in report
    assert "## Evidence" in report
    assert "Coverage reports" in report
    assert "test_case_passed" in report
    assert "E-0001" in report


def test_report_feature_includes_defect_context(tmp_path: Path, capsys) -> None:
    _build_closed_defect(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "report", "feature", "F-0001", "--json"]) == 0
    feature = _json_output(capsys)
    report = Path(feature["path"]).read_text(encoding="utf-8")

    assert [defect["id"] for defect in feature["report"]["defects"]] == ["D-0001"]
    assert [run["id"] for run in feature["report"]["workflow_runs"]] == ["WR-0001"]
    assert [evidence["id"] for evidence in feature["report"]["evidence"]] == ["E-0001", "E-0002"]
    assert "## Defects" in report
    assert "D-0001" in report
    assert "defect_fixed" in report
    assert "defect_closed" in report


def test_report_goal_and_run_include_linked_escalations_and_decisions(tmp_path: Path, capsys) -> None:
    _build_closed_goal(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--run",
        "WR-0001",
        "--severity",
        "high",
        "--question",
        "Can this release proceed?",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--escalation",
        "ESC-0001",
        "--question",
        "Choose release path",
        "--recommendation",
        "Ship locally first",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "resolve",
        "DEC-0001",
        "--selected-option",
        "Ship locally first",
        "--reason",
        "The risk stays local",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--decision",
        "DEC-0001",
        "--summary",
        "Decision recorded",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run = _json_output(capsys)
    run_report = Path(run["path"]).read_text(encoding="utf-8")
    assert run["report"]["escalations"][0]["linked_decision_ids"] == ["DEC-0001"]
    assert run["report"]["decisions"][0]["linked_escalation_ids"] == ["ESC-0001"]
    assert "## Escalations" in run_report
    assert "## Decisions" in run_report
    assert "ESC-0001" in run_report
    assert "DEC-0001" in run_report
    assert "decision_opened" in run_report
    assert "escalation_resolved" in run_report

    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    goal = _json_output(capsys)
    goal_report = Path(goal["path"]).read_text(encoding="utf-8")
    assert goal["report"]["escalations"][0]["linked_decision_ids"] == ["DEC-0001"]
    assert goal["report"]["decisions"][0]["linked_escalation_ids"] == ["ESC-0001"]
    assert "## Escalations" in goal_report
    assert "## Decisions" in goal_report
    assert "ESC-0001" in goal_report
    assert "DEC-0001" in goal_report


def test_report_defect_includes_repair_evidence_and_verification(tmp_path: Path, capsys) -> None:
    _build_closed_defect(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "report", "defect", "D-0001", "--json"]) == 0
    defect = _json_output(capsys)
    report_path = Path(defect["path"])
    report = report_path.read_text(encoding="utf-8")

    assert defect["kind"] == "defect"
    assert defect["report"]["defect"]["status"] == "closed"
    assert "# Defect Report: D-0001" in report
    assert "Login" in report
    assert "defect_fixed" in report
    assert "defect_closed" in report
    assert "E-0001" in report
    assert "E-0002" in report
    assert "V-0001" in report
    assert "WR-0001" in report


def test_report_rejects_unknown_entity(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "report", "goal", "G-9999", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Goal does not exist" in payload["error"]["message"]

    assert main(["--root", str(tmp_path), "report", "feature", "F-9999", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Feature does not exist" in payload["error"]["message"]
