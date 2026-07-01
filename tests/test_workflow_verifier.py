from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


VALID_WORKFLOW = """\
id: dynamic_review
name: "Dynamic Review"
type: closed_loop
version: "0.1.0"
goal:
  description: Review a proposed workflow safely.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review workflow risk.
steps:
  - id: review
    agent: reviewer
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

UNSAFE_WORKFLOW = """\
id: unsafe_review
name: "Unsafe Review"
type: closed_loop
version: "0.1.0"
goal:
  description: Try an unsafe workflow.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review workflow risk.
steps:
  - id: destroy_state
    command: rm -rf .project-loop/project.db
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

UNKNOWN_AGENT_WORKFLOW = """\
id: bad_agent_review
name: "Bad Agent Review"
type: closed_loop
version: "0.1.0"
goal:
  description: Reference an unknown agent.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review workflow risk.
steps:
  - id: review
    agent: missing_reviewer
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_workflow_verify_file_and_template_json_contract(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    source = tmp_path / "workflow.yaml"
    source.write_text(VALID_WORKFLOW, encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "verify", "--file", "workflow.yaml", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["ok"] is True
    verification = payload["verification"]
    assert verification["contract_version"] == "workflow-verification/v1"
    assert verification["target_type"] == "file"
    assert verification["workflow_id"] == "dynamic_review"
    assert verification["errors"] == []
    assert verification["warnings"] == []

    assert main(["--root", str(tmp_path), "workflow", "verify", "--template", "feature_coverage", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["ok"] is True
    assert payload["verification"]["target_type"] == "workflow_template"
    assert payload["verification"]["workflow_id"] == "feature_coverage"


def test_workflow_verify_proposal_reports_unsafe_command_without_mutating(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "unsafe.yaml").write_text(UNSAFE_WORKFLOW, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "unsafe.yaml"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "verify", "--proposal", "WP-0001", "--json"]) == 1
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["verification"]["target_type"] == "workflow_proposal"
    assert any("forbidden fragment: rm -rf" in error for error in payload["verification"]["errors"])
    assert any(".project-loop/project.db" in error for error in payload["verification"]["errors"])

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        approved_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_proposal_approved'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert approved_count == 0


def test_workflow_verify_reports_unknown_agent_reference(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "bad-agent.yaml").write_text(UNKNOWN_AGENT_WORKFLOW, encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "verify", "--file", "bad-agent.yaml", "--json"]) == 1
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert any("references unknown agent: missing_reviewer" in error for error in payload["verification"]["errors"])


def test_workflow_proposal_approve_is_blocked_by_verifier_errors(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "unsafe.yaml").write_text(UNSAFE_WORKFLOW, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "unsafe.yaml"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approve unsafe workflow",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "failed verification" in payload["error"]["message"]
    assert any("forbidden fragment" in error for error in payload["error"]["details"]["errors"])
    assert not (tmp_path / ".project-loop" / "workflows" / "unsafe_review.yaml").exists()


def test_workflow_proposal_approve_records_verifier_summary(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "workflow.yaml").write_text(VALID_WORKFLOW, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "workflow.yaml"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approved",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    assert payload["verification"]["ok"] is True
    assert payload["verification"]["contract_version"] == "workflow-verification/v1"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        event = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'workflow_proposal_approved'"
        ).fetchone()
    finally:
        conn.close()
    event_payload = json.loads(event["payload_json"])
    assert event_payload["verification"]["ok"] is True
    assert event_payload["verification"]["errors"] == []
    assert event_payload["verification"]["check_count"] > 0
