from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


OUTPUT_PATH = ".project-loop/evidence/agent-runs/J-0001/output.md"


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_job(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def _write_output(root: Path, content: str) -> None:
    output_path = root / OUTPUT_PATH
    output_path.write_text(content, encoding="utf-8")


def _job_state(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        job = conn.execute(
            "SELECT status, output_path, summary FROM agent_jobs WHERE id = 'J-0001'"
        ).fetchone()
        evidence_count = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
        event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'agent_output_ingested'"
        ).fetchone()["n"]
        return {"job": dict(job), "evidence_count": evidence_count, "event_count": event_count}
    finally:
        conn.close()


def test_ingest_rejects_empty_agent_output_without_state_change(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    _write_output(tmp_path, "\n\n")
    before = _job_state(tmp_path)

    assert main(["--root", str(tmp_path), "ingest-agent-run", OUTPUT_PATH, "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "Agent output does not satisfy contract."
    assert payload["error"]["details"]["contract_version"] == "agent-output/v1"
    assert "Agent output is empty." in payload["error"]["details"]["errors"]
    assert "Missing required heading: ## Findings." in payload["error"]["details"]["errors"]

    assert _job_state(tmp_path) == before


def test_ingest_rejects_output_missing_required_sections(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    _write_output(tmp_path, "# Summary only\n\nNo required sections.\n")

    assert main(["--root", str(tmp_path), "ingest-agent-run", OUTPUT_PATH, "--json"]) == 2
    payload = _json_output(capsys)
    errors = payload["error"]["details"]["errors"]
    assert "Missing required heading: ## Findings." in errors
    assert "Missing required heading: ## Evidence." in errors
    assert _job_state(tmp_path)["job"]["status"] == "queued"


def test_ingest_rejects_output_without_h1_summary(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    _write_output(tmp_path, "Summary\n\n## Findings\n\n- Found.\n\n## Evidence\n\n- Evidence.\n")

    assert main(["--root", str(tmp_path), "ingest-agent-run", OUTPUT_PATH, "--json"]) == 2
    payload = _json_output(capsys)
    assert (
        "First non-empty line must be a Markdown H1 summary starting with '# '."
        in payload["error"]["details"]["errors"]
    )
    assert _job_state(tmp_path)["evidence_count"] == 0


def test_ingest_valid_output_returns_validation_and_event_contract(tmp_path: Path, capsys) -> None:
    _create_job(tmp_path, capsys)
    _write_output(
        tmp_path,
        "# Valid agent result\n\n"
        "## Findings\n\n"
        "- Found the target behavior.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
    )

    assert main(["--root", str(tmp_path), "ingest-agent-run", OUTPUT_PATH, "--json"]) == 0
    result = _json_output(capsys)
    assert result["contract_version"] == "agent-output/v1"
    assert result["validation"] == {
        "contract_version": "agent-output/v1",
        "ok": True,
        "required_headings": ["## Findings", "## Evidence"],
        "summary": "# Valid agent result",
    }

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert '"contract_version": "agent-output/v1"' in events
    assert '"validation"' in events


def test_agent_output_docs_match_validation_contract() -> None:
    contract = Path("docs/agent-adapter-contract.md").read_text(encoding="utf-8")
    template = Path("docs/agent-output-template.md").read_text(encoding="utf-8")

    for required in ["agent-output/v1", "# Short result summary", "## Findings", "## Evidence"]:
        assert required in template
    assert "validates the file against `agent-output/v1`" in contract
