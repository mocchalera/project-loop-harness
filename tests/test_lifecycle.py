from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_run(root: Path, capsys) -> dict:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    return result


def _db_rows(root: Path, sql: str) -> list[dict]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return [dict(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def test_lifecycle_completes_run_and_closes_goal(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Mapped the surface.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Mapped project surfaces",
        "--output",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--json",
    ]) == 0
    completed_job = _json_output(capsys)
    assert completed_job["status"] == "passed"
    assert completed_job["workflow_started"] is True

    for job_id, summary in [
        ("J-0002", "Wrote user stories"),
        ("J-0003", "Designed tests"),
    ]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "complete",
            job_id,
            "--summary",
            summary,
            "--json",
        ]) == 0
        assert _json_output(capsys)["status"] == "passed"

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
        "pytest passed",
        "--reason",
        "dashboard rendered",
        "--json",
    ]) == 0
    verification = _json_output(capsys)
    assert verification["id"] == "V-0001"
    assert verification["result"] == "approved"

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Feature coverage complete",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "passed"

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
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "closed"

    assert _db_rows(tmp_path, "SELECT id, status FROM agent_jobs ORDER BY id") == [
        {"id": "J-0001", "status": "passed"},
        {"id": "J-0002", "status": "passed"},
        {"id": "J-0003", "status": "passed"},
    ]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "passed"}
    ]
    goal = _db_rows(tmp_path, "SELECT id, status, completion_json FROM goals")[0]
    assert goal["id"] == "G-0001"
    assert goal["status"] == "closed"
    assert json.loads(goal["completion_json"])["closure"]["verification_id"] == "V-0001"

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "agent_job_completed" in events
    assert "workflow_run_started" in events
    assert "verification_recorded" in events
    assert "workflow_run_completed" in events
    assert "goal_closed" in events

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "create_goal"


def test_next_prioritizes_active_workflow_lifecycle(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "continue_workflow"
    assert action["command"] == "pcl jobs read J-0001"

    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "record_verification"
    assert action["command"].startswith("pcl verification record --run WR-0001")

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
        "Manual verification passed",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "complete_workflow"
    assert action["command"].startswith("pcl loop complete WR-0001")


def test_cancel_workflow_cancels_active_jobs_and_goal_can_cancel(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "Superseded by newer run",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["status"] == "cancelled"
    assert result["cancelled_jobs"] == ["J-0001", "J-0002", "J-0003"]

    assert _db_rows(tmp_path, "SELECT DISTINCT status FROM agent_jobs") == [{"status": "cancelled"}]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "cancelled"}
    ]

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "cancel",
        "G-0001",
        "--summary",
        "No longer needed",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "cancelled"

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "workflow_run_cancelled" in events
    assert events.count("agent_job_cancelled") == 3
    assert "goal_cancelled" in events


def test_fail_workflow_cancels_active_jobs(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "fail",
        "WR-0001",
        "--summary",
        "Project command failed",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["status"] == "failed"
    assert result["cancelled_jobs"] == ["J-0001", "J-0002", "J-0003"]

    assert _db_rows(tmp_path, "SELECT DISTINCT status FROM agent_jobs") == [{"status": "cancelled"}]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "failed"}
    ]

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "workflow_run_failed" in events
    assert events.count("agent_job_cancelled") == 3


def test_fail_job_cancels_sibling_active_jobs(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "fail",
        "J-0001",
        "--summary",
        "Mapper failed",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["status"] == "failed"
    assert result["cancelled_jobs"] == ["J-0002", "J-0003"]

    assert _db_rows(tmp_path, "SELECT id, status FROM agent_jobs ORDER BY id") == [
        {"id": "J-0001", "status": "failed"},
        {"id": "J-0002", "status": "cancelled"},
        {"id": "J-0003", "status": "cancelled"},
    ]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "failed"}
    ]

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "agent_job_failed" in events
    assert "workflow_run_failed" in events
    assert events.count("agent_job_cancelled") == 2


def test_lifecycle_rejects_invalid_transitions(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Too early",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be completed until every job has passed" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Too early",
        "--evidence",
        "none",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be closed while workflow runs are active" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "Stop run",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Missing evidence",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "requires --evidence or --verification" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Already cancelled",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot transition from status cancelled" in payload["error"]["message"]
