from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


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


def test_context_pack_for_job_returns_machine_handoff(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--role",
        "implementer",
        "--max-tokens",
        "12000",
        "--json",
    ]) == 0

    payload = _json_output(capsys)
    assert payload["ok"] is True
    pack = payload["context_pack"]
    assert pack["contract_version"] == "context-pack/v1"
    assert pack["target"] == {"type": "agent_job", "id": "J-0001"}
    assert pack["reader_role"] == "implementer"
    assert pack["budget"]["max_tokens"] == 12000
    assert pack["budget"]["approx_char_limit"] == 48000
    assert pack["truncated"] is False
    assert "target_job" in pack["included_sections"]
    assert "agent_prompt" in pack["included_sections"]
    assert pack["source_commands"] == [
        "pcl jobs read J-0001 --json",
        "pcl prompt job J-0001 --json",
        "pcl validate --json",
    ]
    assert ".project-loop/evidence/agent-runs/J-0001/prompt.md" in pack["source_paths"]

    markdown = pack["markdown"]
    assert markdown.startswith("# Context Pack: J-0001")
    assert "## Machine Context Rules" in markdown
    assert "Do not read or parse `.project-loop/dashboard/dashboard.html`" in markdown
    assert ".project-loop/dashboard/dashboard-data.json" in markdown
    assert "## Target Job" in markdown
    assert "| id | J-0001 |" in markdown
    assert "## Workflow Run" in markdown
    assert "## Agent Prompt" in markdown
    assert "# Agent Job J-0001" in markdown


def test_context_pack_non_json_prints_markdown(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "context", "pack", "--job", "J-0001"]) == 0

    captured = capsys.readouterr()
    assert captured.out.startswith("# Context Pack: J-0001")
    assert '"context_pack"' not in captured.out


def test_context_pack_reports_truncation_metadata(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "context",
        "pack",
        "--job",
        "J-0001",
        "--max-tokens",
        "20",
        "--json",
    ]) == 0

    pack = _json_output(capsys)["context_pack"]
    assert pack["truncated"] is True
    assert pack["omitted_sections"]
    assert pack["approx_char_count"] <= pack["budget"]["approx_char_limit"]
    assert pack["markdown"].startswith("# Context Pack: J-0001")
