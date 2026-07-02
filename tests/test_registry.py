from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _create_run(root: Path, capsys) -> None:
    assert main(["--root", str(root), "goal", "create", "--title", "Registry goal", "--json"]) == 0
    _json_output(capsys)
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
    _json_output(capsys)


def _agent_event_types(root: Path) -> list[str]:
    events = [
        json.loads(line)
        for line in (root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return [event["event_type"] for event in events if event["event_type"].startswith("agent_")]


def test_agent_registry_crud_and_events(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "register",
        "--name",
        "codex-worker",
        "--role",
        "implementer",
        "--adapter",
        "codex_exec",
        "--max-concurrency",
        "2",
        "--metadata-json",
        '{"model":"gpt"}',
        "--json",
    ]) == 0
    registered = _json_output(capsys)
    assert registered["id"] == "A-0001"
    assert registered["status"] == "active"
    assert registered["metadata_json"] == '{"model": "gpt"}'

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "register",
        "--name",
        "codex-worker",
        "--role",
        "implementer",
        "--adapter",
        "manual",
        "--json",
    ]) == 2
    duplicate = _json_output(capsys)
    assert duplicate["error"]["code"] == "invalid_input"
    assert "already exists" in duplicate["error"]["message"]

    assert main(["--root", str(tmp_path), "agent", "list", "--status", "active", "--json"]) == 0
    listed = _json_output(capsys)
    assert [agent["id"] for agent in listed["agents"]] == ["A-0001"]
    assert listed["agents"][0]["active_lease_count"] == 0
    assert listed["agents"][0]["active_job_ids"] == []

    assert main(["--root", str(tmp_path), "agent", "read", "A-0001", "--json"]) == 0
    read = _json_output(capsys)["agent"]
    assert read["name"] == "codex-worker"
    assert read["adapter"] == "codex_exec"

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "update",
        "A-0001",
        "--role",
        "reviewer",
        "--adapter",
        "manual",
        "--max-concurrency",
        "1",
        "--status",
        "paused",
        "--metadata-json",
        '{"note":"paused"}',
        "--reason",
        "Switching to manual review",
        "--json",
    ]) == 0
    updated = _json_output(capsys)
    assert updated["agent"]["role"] == "reviewer"
    assert updated["agent"]["adapter"] == "manual"
    assert updated["agent"]["max_concurrency"] == 1
    assert updated["agent"]["status"] == "paused"

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "retire",
        "A-0001",
        "--reason",
        "No longer used",
        "--json",
    ]) == 0
    retired = _json_output(capsys)
    assert retired["agent"]["status"] == "retired"

    assert _agent_event_types(tmp_path) == [
        "agent_registered",
        "agent_updated",
        "agent_retired",
    ]


def test_agent_retire_rejects_active_lease(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "register",
        "--name",
        "lease-holder",
        "--role",
        "implementer",
        "--adapter",
        "manual",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "60",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "retire",
        "A-0001",
        "--reason",
        "Stop worker",
        "--json",
    ]) == 2
    blocked = _json_output(capsys)
    assert blocked["error"]["code"] == "invalid_input"
    assert blocked["error"]["details"]["active_job_ids"] == ["J-0001"]

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "release",
        "J-0001",
        "--reason",
        "Release before retirement",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "retire",
        "A-0001",
        "--reason",
        "Stop worker",
        "--json",
    ]) == 0
    assert _json_output(capsys)["agent"]["status"] == "retired"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute("SELECT assigned_agent_id FROM agent_jobs WHERE id = 'J-0001'").fetchone()
        assert row["assigned_agent_id"] == "A-0001"
    finally:
        conn.close()
