from __future__ import annotations

import json
import sqlite3
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
    assert main(["--root", str(root), "goal", "create", "--title", "Lease goal", "--json"]) == 0
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


def _register_agent(
    root: Path,
    capsys,
    *,
    name: str = "worker",
    max_concurrency: int = 1,
) -> dict:
    assert main([
        "--root",
        str(root),
        "agent",
        "register",
        "--name",
        name,
        "--role",
        "implementer",
        "--adapter",
        "manual",
        "--max-concurrency",
        str(max_concurrency),
        "--json",
    ]) == 0
    return _json_output(capsys)


def _job_row(root: Path, job_id: str) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute("SELECT * FROM agent_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def _event_types(root: Path) -> list[str]:
    events = [
        json.loads(line)
        for line in (root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return [str(event["event_type"]) for event in events]


def test_assign_and_lease_happy_path(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "assign",
        "J-0001",
        "--agent",
        "A-0001",
        "--json",
    ]) == 0
    assigned = _json_output(capsys)
    assert assigned["assigned_agent_id"] == "A-0001"

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
    leased = _json_output(capsys)
    assert leased["status"] == "running"
    assert leased["workflow_started"] is True
    assert leased["lease_expires_at"] > leased["last_heartbeat_at"]

    job = _job_row(tmp_path, "J-0001")
    assert job["status"] == "running"
    assert job["assigned_agent_id"] == "A-0001"
    assert job["lease_expires_at"] == leased["lease_expires_at"]
    assert job["last_heartbeat_at"] == leased["last_heartbeat_at"]

    assert main(["--root", str(tmp_path), "agent", "read", "A-0001", "--json"]) == 0
    agent = _json_output(capsys)["agent"]
    assert agent["active_lease_count"] == 1
    assert agent["active_job_ids"] == ["J-0001"]

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    read = _json_output(capsys)["job"]
    assert read["assigned_agent_id"] == "A-0001"
    assert read["attempts"] == 0

    events = _event_types(tmp_path)
    assert "job_assigned" in events
    assert "job_leased" in events
    assert "workflow_run_started" in events


def test_lease_respects_max_concurrency_and_rejects_non_queued_job(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys, max_concurrency=1)

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
        "jobs",
        "lease",
        "J-0002",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "60",
        "--json",
    ]) == 2
    concurrency = _json_output(capsys)
    assert concurrency["error"]["details"]["active_lease_count"] == 1
    assert concurrency["error"]["details"]["max_concurrency"] == 1

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
    ]) == 2
    non_queued = _json_output(capsys)
    assert non_queued["error"]["details"]["required_status"] == "queued"


def test_heartbeat_extends_and_expired_heartbeat_is_rejected(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys, max_concurrency=2)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "10",
        "--json",
    ]) == 0
    leased = _json_output(capsys)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "heartbeat",
        "J-0001",
        "--ttl-seconds",
        "20",
        "--json",
    ]) == 0
    heartbeat = _json_output(capsys)
    assert heartbeat["lease_expires_at"] > leased["lease_expires_at"]
    assert "job_heartbeat" in _event_types(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0002",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "0",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "jobs", "heartbeat", "J-0002", "--json"]) == 2
    expired = _json_output(capsys)
    assert expired["error"]["details"]["command"] == "pcl jobs reap"


def test_release_requeues_job_and_keeps_assignment(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys)

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
        "jobs",
        "release",
        "J-0001",
        "--reason",
        "operator handoff",
        "--json",
    ]) == 0
    released = _json_output(capsys)
    assert released["status"] == "queued"
    job = _job_row(tmp_path, "J-0001")
    assert job["assigned_agent_id"] == "A-0001"
    assert job["lease_expires_at"] is None
    assert job["last_heartbeat_at"] is None
    assert "job_released" in _event_types(tmp_path)


def test_reap_requeues_then_exhausts_to_blocked_with_escalation(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "0",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "reap_expired_leases"
    assert action["command"] == "pcl jobs reap"
    assert action["priority"] == 44
    assert action["safe_to_run"] is True
    assert action["target"]["expired_job_ids"] == ["J-0001"]

    assert main(["--root", str(tmp_path), "jobs", "reap", "--json"]) == 0
    first = _json_output(capsys)
    assert first["reaped_job_ids"] == ["J-0001"]
    assert first["blocked_job_ids"] == []
    assert _job_row(tmp_path, "J-0001")["attempts"] == 1
    assert _job_row(tmp_path, "J-0001")["status"] == "queued"

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "0",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main(["--root", str(tmp_path), "jobs", "reap", "--json"]) == 0
    second = _json_output(capsys)
    assert second["reaped_job_ids"] == []
    assert second["blocked_job_ids"] == ["J-0001"]
    assert second["escalations"][0]["id"] == "ESC-0001"
    assert second["escalations"][0]["workflow_run_id"] == "WR-0001"
    assert _job_row(tmp_path, "J-0001")["attempts"] == 2
    assert _job_row(tmp_path, "J-0001")["status"] == "blocked"
    events = _event_types(tmp_path)
    assert "job_lease_expired" in events
    assert "job_lease_exhausted" in events
    assert "escalation_opened" in events


def test_reap_processes_expired_leases_in_job_id_order(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys, max_concurrency=1)

    for job_id in ["J-0002", "J-0001"]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "lease",
            job_id,
            "--agent",
            "A-0001",
            "--ttl-seconds",
            "0",
            "--json",
        ]) == 0
        _json_output(capsys)

    assert main(["--root", str(tmp_path), "jobs", "reap", "--json"]) == 0
    reaped = _json_output(capsys)
    assert reaped["reaped_job_ids"] == ["J-0001", "J-0002"]


def test_terminal_job_paths_clear_lease_fields(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys, max_concurrency=3)

    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "lease",
            job_id,
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
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "done",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "cancel",
        "J-0002",
        "--summary",
        "cancelled",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "fail",
        "J-0003",
        "--summary",
        "failed",
        "--json",
    ]) == 0
    _json_output(capsys)

    for job_id in ["J-0001", "J-0002", "J-0003"]:
        job = _job_row(tmp_path, job_id)
        assert job["lease_expires_at"] is None
        assert job["last_heartbeat_at"] is None


def test_validator_warns_for_expired_running_lease_and_strict_errors(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
    _register_agent(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "lease",
        "J-0001",
        "--agent",
        "A-0001",
        "--ttl-seconds",
        "0",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["ok"] is True
    assert any("expired lease" in warning for warning in normal["warnings"])

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    strict = _json_output(capsys)
    assert strict["ok"] is False
    assert any("Strict mode treats warning as error" in error for error in strict["errors"])


def test_validator_detects_agent_reference_retired_agent_and_concurrency(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_run(tmp_path, capsys)
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
    _json_output(capsys)
    _register_agent(tmp_path, capsys, name="retired-holder", max_concurrency=1)
    _register_agent(tmp_path, capsys, name="overloaded", max_concurrency=1)

    future = "2999-01-01T00:00:00+00:00"
    raw = sqlite3.connect(tmp_path / ".project-loop" / "project.db")
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute(
            """
            UPDATE agent_jobs
            SET status = 'running', assigned_agent_id = ?, lease_expires_at = ?, last_heartbeat_at = ?
            WHERE id = 'J-0001'
            """,
            ("A-9999", future, future),
        )
        raw.execute("UPDATE agents SET status = 'retired' WHERE id = 'A-0001'")
        raw.execute(
            """
            UPDATE agent_jobs
            SET status = 'running', assigned_agent_id = ?, lease_expires_at = ?, last_heartbeat_at = ?
            WHERE id = 'J-0002'
            """,
            ("A-0001", future, future),
        )
        raw.execute(
            """
            UPDATE agent_jobs
            SET status = 'running', assigned_agent_id = ?, lease_expires_at = ?, last_heartbeat_at = ?
            WHERE id IN ('J-0003', 'J-0004')
            """,
            ("A-0002", future, future),
        )
        raw.commit()
    finally:
        raw.close()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 1
    result = _json_output(capsys)
    assert any("references missing agent A-9999" in error for error in result["errors"])
    assert any("Retired agent A-0001 holds active lease" in error for error in result["errors"])
    assert any("Active agent A-0002 has 2 active leases" in warning for warning in result["warnings"])
