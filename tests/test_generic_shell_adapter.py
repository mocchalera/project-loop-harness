from __future__ import annotations

import json
import shlex
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


def _generic_shell_command(root: Path, capsys) -> dict:
    assert main([
        "--root",
        str(root),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "generic_shell",
        "--json",
    ]) == 0
    return _json_output(capsys)["agent_command"]


def test_generic_shell_command_uses_env_stdin_stdout_and_ingest(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project with spaces"
    _create_job(root, capsys)

    agent_command = _generic_shell_command(root, capsys)
    command = agent_command["command"]
    argv = shlex.split(command)

    assert agent_command["adapter"] == "generic_shell"
    assert agent_command["prompt_path"] == EXPECTED_PROMPT_PATH
    assert agent_command["output_path"] == EXPECTED_OUTPUT_PATH
    assert agent_command["ingest_command"].endswith(f"--root {shlex.quote(str(root))}")
    assert argv[:2] == ["bash", "-lc"]
    script = argv[2]
    assert "set -euo pipefail" in script
    assert "mkdir -p" in script
    assert "PCL_AGENT_COMMAND" in script
    assert "sh -c \"$PCL_AGENT_COMMAND\"" in script
    assert f"< {shlex.quote(str(root / EXPECTED_PROMPT_PATH))}" in script
    assert f"> {shlex.quote(str(root / EXPECTED_OUTPUT_PATH))}" in script
    assert f"test -s {shlex.quote(str(root / EXPECTED_OUTPUT_PATH))}" in script
    assert agent_command["ingest_command"] in script
    assert "agent-output/v1" in agent_command["instructions"]
    assert agent_command["ingest_command"] in agent_command["instructions"]


def test_generic_shell_command_generation_does_not_mutate_job_state(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    before = _job_state(tmp_path)
    agent_command = _generic_shell_command(tmp_path, capsys)
    after = _job_state(tmp_path)

    assert agent_command["command"] is not None
    assert before == after


def test_generic_shell_happy_path_ingests_output_as_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    job = _json_output(capsys)["job"]
    assert job["id"] == "J-0001"

    assert main(["--root", str(tmp_path), "prompt", "job", "J-0001", "--json"]) == 0
    prompt_payload = _json_output(capsys)
    assert prompt_payload["prompt"] == job["prompt"]

    agent_command = _generic_shell_command(tmp_path, capsys)
    output_path = tmp_path / agent_command["output_path"]
    output_path.write_text(
        "# Generic shell result\n\n"
        "## Findings\n\n"
        "- The generic shell adapter emitted a stable handoff command.\n\n"
        "## Evidence\n\n"
        f"- `{agent_command['prompt_path']}`\n",
        encoding="utf-8",
    )

    ingest_args = shlex.split(agent_command["ingest_command"])[1:]
    assert main(["--root", str(tmp_path), *ingest_args, "--json"]) == 0
    ingested = _json_output(capsys)
    assert ingested["job_id"] == "J-0001"
    assert ingested["contract_version"] == "agent-output/v1"
    assert ingested["evidence_id"] == "E-0001"
    assert ingested["output_path"] == EXPECTED_OUTPUT_PATH
    assert ingested["summary"] == "# Generic shell result"

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run_report = _json_output(capsys)
    assert [row["id"] for row in run_report["report"]["evidence"]] == ["E-0001"]
    assert any(event["event_type"] == "agent_output_ingested" for event in run_report["report"]["events"])


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
