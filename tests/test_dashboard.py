from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _read_dashboard(root: Path) -> str:
    return (root / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")


def _read_dashboard_data(root: Path) -> dict:
    return json.loads(
        (root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )


def test_dashboard_renders_control_panels_and_workflow_state(tmp_path: Path) -> None:
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
    assert main(["--root", str(tmp_path), "render"]) == 0

    html = _read_dashboard(tmp_path)
    assert "<!doctype html>" in html
    assert "Source DB:" in html
    assert "Next Human Action" in html
    assert "Risk &amp; Blockers" in html
    assert "Current Goal" in html
    assert "Active Workflow" in html
    assert "Budget Usage" in html
    assert "Active Agent Jobs" in html
    assert "Verification Results" in html
    assert "Escalation Queue" in html
    assert "Evidence Links" in html
    assert "Recent Events" in html
    assert "Validation OK" in html
    assert "WR-0001" in html
    assert "J-0001" in html
    assert ".project-loop/evidence/agent-runs/J-0001/prompt.md" in html
    assert "pcl jobs read J-0001" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html

    data = _read_dashboard_data(tmp_path)
    assert data["source_db"] == str(tmp_path / ".project-loop" / "project.db")
    assert data["validation"] == {"errors": [], "ok": True, "warnings": []}
    assert data["active_workflow"]["id"] == "WR-0001"
    assert data["active_workflow"]["budget"]["max_iterations"] == 2
    assert data["active_agent_jobs"][0]["id"] == "J-0001"
    assert data["counts"]["queued_jobs"] == 3
    assert data["next_action"]["type"] == "continue_workflow"
    assert data["risk_summary"] == {
        "blocking": False,
        "highest_severity": "none",
        "items": [],
    }


def test_dashboard_surfaces_validation_warnings(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    skill_path = tmp_path / ".agents" / "skills" / "project-control-loop" / "SKILL.md"
    skill_path.unlink()

    assert main(["--root", str(tmp_path), "render"]) == 0

    html = _read_dashboard(tmp_path)
    data = _read_dashboard_data(tmp_path)
    assert "Validation Warnings" in html
    assert "Missing project-control-loop Skill" in html
    assert data["risk_summary"]["highest_severity"] == "low"
    assert data["risk_summary"]["items"][0]["type"] == "validation_warnings"
    assert data["risk_summary"]["items"][0]["blocking"] is False


def test_dashboard_surfaces_open_human_queue_risks(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "critical",
        "--question",
        "Which path should ship?",
        "--recommendation",
        "Choose the reversible path",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Which path should ship?",
        "--recommendation",
        "Choose the reversible path",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    html = _read_dashboard(tmp_path)
    data = _read_dashboard_data(tmp_path)
    items_by_type = {item["type"]: item for item in data["risk_summary"]["items"]}

    assert data["risk_summary"]["blocking"] is True
    assert data["risk_summary"]["highest_severity"] == "critical"
    assert items_by_type["open_escalation"]["requires_human"] is True
    assert items_by_type["open_escalation"]["target"] == {"type": "escalation", "id": "ESC-0001"}
    assert items_by_type["open_decision"]["requires_human"] is True
    assert items_by_type["open_decision"]["target"] == {"type": "decision", "id": "DEC-0001"}
    assert "Risk &amp; Blockers" in html
    assert "Open escalation ESC-0001" in html
    assert "Open decision DEC-0001" in html


def test_dashboard_risk_summary_includes_open_items_outside_table_limit(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Old open decision?",
        "--recommendation",
        "Keep tracking it",
    ]) == 0
    for index in range(2, 22):
        decision_id = f"DEC-{index:04d}"
        assert main([
            "--root",
            str(tmp_path),
            "decision",
            "open",
            "--question",
            f"Resolved filler decision {index}?",
            "--recommendation",
            "Resolve it",
        ]) == 0
        assert main([
            "--root",
            str(tmp_path),
            "decision",
            "resolve",
            decision_id,
            "--selected-option",
            "Resolved",
            "--reason",
            "Filler row",
        ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    open_decision_items = [
        item for item in data["risk_summary"]["items"] if item["type"] == "open_decision"
    ]

    assert data["counts"]["open_decisions"] == 1
    assert all(decision["id"] != "DEC-0001" for decision in data["decisions"])
    assert open_decision_items == [
        {
            "type": "open_decision",
            "severity": "high",
            "blocking": True,
            "requires_human": True,
            "summary": "Open decision DEC-0001: Old open decision?",
            "command": "pcl decision resolve DEC-0001 --selected-option 'Record the choice' --reason 'Record the reason'",
            "target": {"type": "decision", "id": "DEC-0001"},
            "count": 1,
        }
    ]


def test_dashboard_surfaces_failed_run_and_job_risks(tmp_path: Path) -> None:
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
        "jobs",
        "fail",
        "J-0001",
        "--summary",
        "mapper failed",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    items_by_type = {item["type"]: item for item in data["risk_summary"]["items"]}

    assert data["risk_summary"]["highest_severity"] == "high"
    assert items_by_type["failed_workflow_run"]["target"] == {"type": "workflow_run", "id": "WR-0001"}
    assert items_by_type["failed_agent_job"]["target"] == {"type": "agent_job", "id": "J-0001"}
    assert items_by_type["failed_agent_job"]["command"] == "pcl jobs read J-0001"


def test_dashboard_all_jobs_preserves_output_path_after_run_is_inactive(tmp_path: Path) -> None:
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
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Captured output before run cancellation.\n\n"
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
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "cancel remaining jobs",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0

    data = _read_dashboard_data(tmp_path)
    jobs_by_id = {job["id"]: job for job in data["agent_jobs"]}
    assert data["active_agent_jobs"] == []
    assert jobs_by_id["J-0001"]["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert jobs_by_id["J-0001"]["latest_evidence_id"] == "E-0001"


def test_dashboard_data_is_deterministic_for_unchanged_state(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0
    first_html = _read_dashboard(tmp_path)
    first_data = _read_dashboard_data(tmp_path)

    assert main(["--root", str(tmp_path), "render"]) == 0
    assert _read_dashboard(tmp_path) == first_html
    assert _read_dashboard_data(tmp_path) == first_data
