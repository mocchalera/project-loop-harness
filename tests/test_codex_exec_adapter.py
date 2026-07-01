from __future__ import annotations

import json
import shlex
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def _codex_command(root: Path, capsys) -> dict:
    assert main([
        "--root",
        str(root),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "codex_exec",
        "--json",
    ]) == 0
    return _json_output(capsys)["agent_command"]


def test_codex_exec_command_uses_fail_fast_stdin_and_output_file(tmp_path: Path, capsys) -> None:
    root = tmp_path / "project with spaces"
    _create_job(root, capsys)

    agent_command = _codex_command(root, capsys)
    command = agent_command["command"]
    argv = shlex.split(command)

    assert argv[:2] == ["bash", "-lc"]
    script = argv[2]
    assert "set -euo pipefail" in script
    assert "mkdir -p" in script
    assert "codex exec" in script
    assert "--cd" in script
    assert str(root) in script
    assert "--output-last-message" in script
    assert str(root / agent_command["output_path"]) in script
    assert f"- < {shlex.quote(str(root / agent_command['prompt_path']))}" in script
    assert "$(cat" not in script
    assert f"> {shlex.quote(str(root / agent_command['output_path']))}" not in script
    assert agent_command["ingest_command"] in script


def test_codex_exec_command_generation_does_not_mutate_job_state(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    before = _job_state(tmp_path)
    agent_command = _codex_command(tmp_path, capsys)
    after = _job_state(tmp_path)

    assert agent_command["command"] is not None
    assert before == after


def _job_state(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        job = conn.execute(
            "SELECT status, output_path, ended_at FROM agent_jobs WHERE id = 'J-0001'"
        ).fetchone()
        evidence_count = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'agent_output_ingested'"
        ).fetchone()["n"]
        return {"job": dict(job), "evidence_count": evidence_count, "event_count": event_count}
    finally:
        conn.close()
