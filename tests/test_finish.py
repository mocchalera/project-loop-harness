from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


COUNT_TABLES = [
    "goals",
    "workflow_runs",
    "agent_jobs",
    "verifications",
    "events",
    "evidence",
    "features",
    "user_stories",
    "test_cases",
    "defects",
]


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_run(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def _complete_jobs(root: Path, capsys) -> None:
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
    capsys.readouterr()


def _approve_run(root: Path, capsys) -> None:
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
        "Manual verification passed",
    ]) == 0
    capsys.readouterr()


def _complete_run(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Workflow reviewed and completed",
    ]) == 0
    capsys.readouterr()


def _close_goal(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Goal reviewed and closed",
        "--verification",
        "V-0001",
    ]) == 0
    capsys.readouterr()


def _state_counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in COUNT_TABLES
        }
    finally:
        conn.close()
    counts["events_jsonl"] = len((root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines())
    return counts


def _finish_payload(capsys) -> dict:
    payload = _json_output(capsys)
    assert payload["ok"] is True
    return payload["finish"]


def test_finish_plans_active_workflow_without_mutation(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["target"] == {"run": "WR-0001", "goal": "G-0001"}
    assert finish["finished"] is False
    assert finish["next_command"] == "pcl jobs read J-0001"
    assert finish["remaining_steps"] == [
        {
            "type": "continue_workflow",
            "command": "pcl jobs read J-0001",
            "reason": "A workflow run is already active and has queued or running jobs.",
            "requires_human": False,
            "safe_to_run": True,
        }
    ]
    assert _state_counts(tmp_path) == before

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    step = finish["remaining_steps"][0]
    assert step == {key: action[key] for key in step}


def test_finish_execute_with_pending_assertion_runs_nothing(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main(["--root", str(tmp_path), "finish", "--execute", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["finished"] is False
    assert finish["next_command"].startswith("pcl verification record --run WR-0001")
    assert finish["remaining_steps"][0]["type"] == "record_verification"
    assert finish["remaining_steps"][0]["requires_human"] is True
    assert finish["remaining_steps"][0]["safe_to_run"] is False
    assert finish["executed"] == []
    assert finish["changed"] is False
    assert _state_counts(tmp_path) == before


def test_finish_plans_goal_close_after_passed_run(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _approve_run(tmp_path, capsys)
    _complete_run(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["target"] == {"run": "WR-0001", "goal": "G-0001"}
    assert finish["finished"] is False
    assert finish["remaining_steps"] == [
        {
            "type": "close_goal",
            "command": "pcl goal close G-0001 --summary 'Summarize completed goal' --verification V-0001",
            "reason": "The workflow run has passed and its goal is still open.",
            "requires_human": True,
            "safe_to_run": False,
        }
    ]


def test_finish_execute_closed_loop_runs_generation_tail(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _approve_run(tmp_path, capsys)
    _complete_run(tmp_path, capsys)
    _close_goal(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "finish", "--execute", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["target"] == {"run": None, "goal": None}
    assert finish["finished"] is True
    assert finish["remaining_steps"] == []
    assert finish["next_command"] is None
    assert finish["executed"] == [
        {"command": "pcl validate --strict", "ok": True},
        {"command": "pcl render", "ok": True},
    ]
    assert finish["changed"] is True

    assert main(["--root", str(tmp_path), "finish", "--execute", "--json"]) == 0
    rerun = _finish_payload(capsys)
    assert rerun["finished"] is True
    assert rerun["remaining_steps"] == []
    assert rerun["executed"] == [
        {"command": "pcl validate --strict", "ok": True},
        {"command": "pcl render", "ok": True},
    ]


def test_finish_no_active_run_and_no_open_goal_is_finished(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish == {
        "target": {"run": None, "goal": None},
        "finished": True,
        "remaining_steps": [],
        "next_command": None,
    }
