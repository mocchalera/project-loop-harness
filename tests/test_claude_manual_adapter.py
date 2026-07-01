from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


EXPECTED_OUTPUT_PATH = ".project-loop/evidence/agent-runs/J-0001/output.md"
EXPECTED_PROMPT_PATH = ".project-loop/evidence/agent-runs/J-0001/prompt.md"


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def test_claude_manual_adapter_instructions_are_actionable(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "claude_manual",
        "--json",
    ]) == 0
    agent_command = _json_output(capsys)["agent_command"]
    instructions = agent_command["instructions"]

    assert agent_command["adapter"] == "claude_manual"
    assert agent_command["command"] is None
    assert agent_command["prompt_path"] == EXPECTED_PROMPT_PATH
    assert agent_command["output_path"] == EXPECTED_OUTPUT_PATH
    assert agent_command["ingest_command"] == f"pcl ingest-agent-run {EXPECTED_OUTPUT_PATH}"
    assert "Claude Code manual handoff:" in instructions
    assert EXPECTED_PROMPT_PATH in instructions
    assert EXPECTED_OUTPUT_PATH in instructions
    assert agent_command["ingest_command"] in instructions
    assert "agent-output/v1" in instructions
    assert "`# Short result summary`" in instructions
    assert "`## Findings`" in instructions
    assert "`## Evidence`" in instructions
    assert "Do not edit `.project-loop/project.db` directly." in instructions
    assert "pcl` does not execute Claude Code automatically" in instructions


def test_claude_manual_command_generation_does_not_mutate_job_state(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    before = _job_state(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "claude_manual",
        "--json",
    ]) == 0
    _json_output(capsys)

    assert _job_state(tmp_path) == before


def test_claude_manual_docs_match_adapter_contract() -> None:
    contract = Path("docs/agent-adapter-contract.md").read_text(encoding="utf-8")

    for required in [
        "Claude Manual Adapter",
        "Claude Code manual handoff",
        "agent-output/v1",
        ".project-loop/evidence/agent-runs/<job_id>/output.md",
        "pcl ingest-agent-run",
        "does not execute Claude Code",
    ]:
        assert required in contract


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
