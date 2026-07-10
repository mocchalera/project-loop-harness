from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_readme_golden_path_runs_end_to_end(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "doctor"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "create",
        "--title",
        "Reach basic feature coverage",
    ]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    next_action = _json_output(capsys)
    assert next_action["type"] == "continue_workflow"
    assert next_action["priority"] == 40

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001"]) == 0
    for job_id, summary in [
        ("J-0001", "Mapped project surfaces"),
        ("J-0002", "Wrote user stories"),
        ("J-0003", "Designed test cases"),
    ]:
        assert main(["--root", str(tmp_path), "jobs", "complete", job_id, "--summary", summary]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--explain"]) == 0
    assert "Next action: record_verification" in capsys.readouterr().out

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "Reviewed generated coverage",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Feature coverage complete",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Coverage goal done",
        "--verification",
        "V-0001",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True
    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    goal_report = _json_output(capsys)
    assert Path(goal_report["path"]).exists()
    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run_report = _json_output(capsys)
    assert Path(run_report["path"]).exists()
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    render = _json_output(capsys)
    assert Path(render["path"]).exists()
    assert Path(render["data_path"]).exists()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "idle"


def test_readme_human_decision_branch_links_escalation_and_decision(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main(["--root", str(tmp_path), "jobs", "complete", job_id, "--summary", f"Completed {job_id}"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "needs_human",
        "--reason",
        "Product decision required",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "open_escalation"

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
        "What should ship?",
        "--recommendation",
        "Choose the safest reversible path",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--escalation",
        "ESC-0001",
        "--question",
        "Which path should we take?",
        "--recommendation",
        "Choose the safest reversible path",
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
        "Risk stays local",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--decision",
        "DEC-0001",
        "--summary",
        "Human decision recorded",
        "--json",
    ]) == 0
    resolved = _json_output(capsys)
    assert resolved["decision_id"] == "DEC-0001"

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    dashboard_data = json.loads((tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    assert dashboard_data["decisions"][0]["linked_escalation_ids"] == ["ESC-0001"]
    assert dashboard_data["escalations"][0]["linked_decision_ids"] == ["DEC-0001"]
