from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
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
    capsys.readouterr()


def test_prompt_job_prints_complete_prompt(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "prompt", "job", "J-0001"]) == 0

    captured = capsys.readouterr()
    assert "# Agent Job J-0001" in captured.out
    assert "Role: mapper" in captured.out
    assert "Do not edit `.project-loop/project.db` directly." in captured.out
    assert "agent-output/v1" in captured.out
    assert "# Short result summary" in captured.out
    assert "## Findings" in captured.out
    assert "## Evidence" in captured.out
    assert "## Recommended pcl Commands" in captured.out
    assert "pcl feature add" in captured.out

    assert main(["--root", str(tmp_path), "prompt", "job", "J-0001", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["ok"] is True
    assert payload["job_id"] == "J-0001"
    assert payload["workflow_run_id"] == "WR-0001"
    assert payload["workflow_id"] == "feature_coverage"
    assert payload["role"] == "mapper"
    assert payload["status"] == "queued"
    assert payload["prompt_path"] == ".project-loop/evidence/agent-runs/J-0001/prompt.md"
    assert payload["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert payload["ingest_command"] == "pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md"
    assert "agent-output/v1" in payload["expected_output_format"]
    assert payload["prompt"].startswith("# Agent Job J-0001")
    assert "The first non-empty line must be the H1 summary." in payload["prompt"]
    assert 'pcl feature add --name "..."' in payload["prompt"]


def test_agent_command_adapters(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "codex_exec",
        "--json",
    ]) == 0
    codex = _json_output(capsys)["agent_command"]
    assert codex["contract_version"] == "agent-adapter-command/v1"
    assert codex["adapter"] == "codex_exec"
    assert codex["command"].startswith("bash -lc ")
    assert "set -euo pipefail" in codex["command"]
    assert "codex exec" in codex["command"]
    assert "--output-last-message" in codex["command"]
    assert "pcl ingest-agent-run" in codex["command"]
    assert codex["ingest_command"] in codex["command"]
    assert "$(cat" not in codex["command"]
    assert codex["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert "Markdown report" in codex["expected_output_format"]

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
    claude = _json_output(capsys)["agent_command"]
    assert claude["adapter"] == "claude_manual"
    assert claude["ingest_command"] == "pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md"
    assert claude["command"] is None
    assert "Claude Code" in claude["instructions"]
    assert "agent-output/v1" in claude["instructions"]
    assert "## Findings" in claude["instructions"]
    assert "## Evidence" in claude["instructions"]

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "generic_shell",
        "--json",
    ]) == 0
    shell = _json_output(capsys)["agent_command"]
    assert shell["adapter"] == "generic_shell"
    assert shell["command"].startswith("bash -lc ")
    assert "PCL_AGENT_COMMAND" in shell["command"]
    assert "pcl ingest-agent-run" in shell["command"]
    assert shell["ingest_command"] in shell["command"]
    assert shell["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "manual",
    ]) == 0
    manual = capsys.readouterr()
    assert "pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md" in manual.out


def test_ingest_agent_run_records_evidence_and_updates_job(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Found the login surface.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["job_id"] == "J-0001"
    assert result["contract_version"] == "agent-output/v1"
    assert result["evidence_id"] == "E-0001"
    assert result["summary"] == "# Mapper result"
    assert result["status"] == "passed"
    assert result["validation"]["ok"] is True

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        job = conn.execute(
            "SELECT status, output_path, summary FROM agent_jobs WHERE id = 'J-0001'"
        ).fetchone()
        assert dict(job) == {
            "status": "passed",
            "output_path": ".project-loop/evidence/agent-runs/J-0001/output.md",
            "summary": "# Mapper result",
        }
        run = conn.execute("SELECT status FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
        assert run["status"] == "running"
        evidence = conn.execute("SELECT id, type, path, summary FROM evidence").fetchone()
        assert dict(evidence) == {
            "id": "E-0001",
            "type": "agent_output",
            "path": ".project-loop/evidence/agent-runs/J-0001/output.md",
            "summary": "# Mapper result",
        }
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    job_payload = _json_output(capsys)["job"]
    assert job_payload["status"] == "passed"
    assert job_payload["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert job_payload["evidence_ids"] == ["E-0001"]
    assert job_payload["latest_evidence_id"] == "E-0001"
    assert job_payload["latest_evidence_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert job_payload["evidence"] == [
        {
            "id": "E-0001",
            "type": "agent_output",
            "path": ".project-loop/evidence/agent-runs/J-0001/output.md",
            "command": None,
            "summary": "# Mapper result",
            "created_at": job_payload["evidence"][0]["created_at"],
        }
    ]

    assert main(["--root", str(tmp_path), "jobs", "list", "--json"]) == 0
    listed_job = _json_output(capsys)["jobs"][0]
    assert listed_job["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert listed_job["evidence_ids"] == ["E-0001"]
    assert listed_job["latest_evidence_id"] == "E-0001"

    assert main(["--root", str(tmp_path), "render"]) == 0
    dashboard = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(
        encoding="utf-8"
    )
    dashboard_data = json.loads(
        (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
    assert "E-0001" in dashboard
    assert "agent_output" in dashboard
    assert ".project-loop/evidence/agent-runs/J-0001/output.md" in dashboard
    assert dashboard_data["agent_jobs"][0]["latest_evidence_id"] == "E-0001"
    assert dashboard_data["agent_jobs"][0]["evidence_ids"] == ["E-0001"]

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "agent_output_ingested" in events


def test_repeated_agent_output_ingests_are_visible_from_job_read(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"

    for summary in ["# First mapper result", "# Second mapper result"]:
        output_path.write_text(
            f"{summary}\n\n"
            "## Findings\n\n"
            "- Updated mapper output.\n\n"
            "## Evidence\n\n"
            "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
            encoding="utf-8",
        )
        assert main([
            "--root",
            str(tmp_path),
            "ingest-agent-run",
            ".project-loop/evidence/agent-runs/J-0001/output.md",
            "--json",
        ]) == 0
        _json_output(capsys)

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    job = _json_output(capsys)["job"]
    assert job["summary"] == "# Second mapper result"
    assert job["evidence_ids"] == ["E-0001", "E-0002"]
    assert [row["id"] for row in job["evidence"]] == ["E-0001", "E-0002"]
    assert job["latest_evidence_id"] == "E-0002"
    assert job["latest_evidence_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"


def test_ingest_agent_run_rejects_late_output_after_run_cancel(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "cancelled",
    ]) == 0
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Late mapper result\n\n"
        "## Findings\n\n"
        "- This output arrived after cancellation.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot ingest output while status is cancelled" in payload["error"]["message"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        job = conn.execute("SELECT status, output_path FROM agent_jobs WHERE id = 'J-0001'").fetchone()
        evidence_count = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        ingest_events = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'agent_output_ingested'"
        ).fetchone()["n"]
        assert dict(job) == {"status": "cancelled", "output_path": None}
        assert evidence_count == 0
        assert ingest_events == 0
    finally:
        conn.close()


def test_ingest_agent_run_rejects_late_output_after_run_failure(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "fail",
        "WR-0001",
        "--summary",
        "failed",
    ]) == 0
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Late mapper result\n\n"
        "## Findings\n\n"
        "- This output arrived after failure.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot ingest output while status is cancelled" in payload["error"]["message"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        job = conn.execute("SELECT status, output_path FROM agent_jobs WHERE id = 'J-0001'").fetchone()
        evidence_count = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        assert dict(job) == {"status": "cancelled", "output_path": None}
        assert evidence_count == 0
    finally:
        conn.close()


def test_ingest_agent_run_rejects_external_agent_runs_path(
    tmp_path: Path,
    capsys,
) -> None:
    _create_job(tmp_path, capsys)
    external_output = tmp_path.parent / f"{tmp_path.name}-external" / "agent-runs" / "J-0001" / "output.md"
    external_output.parent.mkdir(parents=True)
    external_output.write_text(
        "# External mapper result\n\n"
        "## Findings\n\n"
        "- This output is outside the project evidence directory.\n\n"
        "## Evidence\n\n"
        "- `/tmp/external/agent-runs/J-0001/output.md`\n",
        encoding="utf-8",
    )
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        str(external_output),
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert ".project-loop/evidence/agent-runs/<job_id>/output.md" in payload["error"]["message"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        job = conn.execute("SELECT status, output_path FROM agent_jobs WHERE id = 'J-0001'").fetchone()
        evidence_count = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        assert dict(job) == {"status": "queued", "output_path": None}
        assert evidence_count == 0
    finally:
        conn.close()


def test_ingest_agent_run_rejects_unknown_path_shape(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    output_path = tmp_path / "output.md"
    output_path.write_text("No job path\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "ingest-agent-run", "output.md", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Cannot infer agent job id" in payload["error"]["message"]
