from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


EXPECTED_OUTPUT_PATH = ".project-loop/evidence/agent-runs/J-0001/output.md"
EXPECTED_PROMPT_PATH = ".project-loop/evidence/agent-runs/J-0001/prompt.md"
EXPECTED_KEYS = {
    "adapter",
    "command",
    "contract_version",
    "expected_output_format",
    "ingest_command",
    "instructions",
    "job_id",
    "output_path",
    "prompt_path",
}


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def test_agent_command_contract_is_stable_for_all_adapters(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    for adapter in ["manual", "codex_exec", "claude_manual", "generic_shell"]:
        assert main([
            "--root",
            str(tmp_path),
            "agent",
            "command",
            "J-0001",
            "--adapter",
            adapter,
            "--json",
        ]) == 0
        payload = _json_output(capsys)
        command = payload["agent_command"]

        assert payload["ok"] is True
        assert set(command) == EXPECTED_KEYS
        assert command["contract_version"] == "agent-adapter-command/v1"
        assert command["adapter"] == adapter
        assert command["job_id"] == "J-0001"
        assert command["prompt_path"] == EXPECTED_PROMPT_PATH
        assert command["output_path"] == EXPECTED_OUTPUT_PATH
        assert command["ingest_command"].startswith(f"pcl ingest-agent-run {EXPECTED_OUTPUT_PATH}")
        assert "Markdown report" in command["expected_output_format"]
        assert EXPECTED_OUTPUT_PATH in command["instructions"] or command["command"]
        if adapter == "codex_exec":
            assert command["command"] is not None
            assert EXPECTED_OUTPUT_PATH in command["command"]
            assert command["ingest_command"] in command["command"]
            assert "--output-last-message" in command["command"]
        elif adapter == "generic_shell":
            assert command["command"] is not None
            assert EXPECTED_OUTPUT_PATH in command["command"]
            assert command["ingest_command"] in command["command"]
            assert "PCL_AGENT_COMMAND" in command["command"]
            assert "sh -c" in command["command"]
            assert "agent-output/v1" in command["instructions"]
        else:
            assert command["command"] is None


def test_agent_handoff_happy_path_ingests_evidence_and_reports(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    job = _json_output(capsys)["job"]
    assert job["id"] == "J-0001"
    assert "Role: mapper" in job["prompt"]

    assert main(["--root", str(tmp_path), "prompt", "job", "J-0001", "--json"]) == 0
    prompt_payload = _json_output(capsys)
    assert prompt_payload["job_id"] == "J-0001"
    assert prompt_payload["prompt"] == job["prompt"]

    assert main([
        "--root",
        str(tmp_path),
        "agent",
        "command",
        "J-0001",
        "--adapter",
        "manual",
        "--json",
    ]) == 0
    command = _json_output(capsys)["agent_command"]
    output_path = tmp_path / command["output_path"]
    output_path.write_text(
        "# Adapter contract result\n\n"
        "## Findings\n\n"
        "- Mapped the feature surface.\n\n"
        "## Evidence\n\n"
        f"- `{command['prompt_path']}`\n",
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), *command["ingest_command"].split()[1:], "--json"]) == 0
    ingested = _json_output(capsys)
    assert ingested["job_id"] == "J-0001"
    assert ingested["contract_version"] == "agent-output/v1"
    assert ingested["evidence_id"] == "E-0001"
    assert ingested["output_path"] == EXPECTED_OUTPUT_PATH
    assert ingested["summary"] == "# Adapter contract result"
    assert ingested["validation"]["required_headings"] == ["## Findings", "## Evidence"]

    assert main(["--root", str(tmp_path), "report", "run", "WR-0001", "--json"]) == 0
    run_report = _json_output(capsys)
    assert [row["id"] for row in run_report["report"]["evidence"]] == ["E-0001"]
    assert any(event["event_type"] == "agent_output_ingested" for event in run_report["report"]["events"])
    report_markdown = Path(run_report["path"]).read_text(encoding="utf-8")
    assert "agent_output" in report_markdown
    assert EXPECTED_OUTPUT_PATH in report_markdown


def test_agent_adapter_docs_match_contract() -> None:
    contract = Path("docs/agent-adapter-contract.md").read_text(encoding="utf-8")
    template = Path("docs/agent-output-template.md").read_text(encoding="utf-8")

    for required in [
        "agent-adapter-command/v1",
        "pcl jobs read J-0001",
        "pcl prompt job J-0001",
        "pcl agent command J-0001 --adapter manual --json",
        "pcl agent command J-0001 --adapter generic_shell --json",
        EXPECTED_OUTPUT_PATH,
        "pcl ingest-agent-run",
        "No automatic external execution.",
        "agent-output/v1",
        "codex exec --cd",
        "Claude Manual Adapter",
        "Generic Shell Adapter",
        "latest_evidence_id",
        "agent_output_ingested",
    ]:
        assert required in contract
    assert "# Short result summary" in template
