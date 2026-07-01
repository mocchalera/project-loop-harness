from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


SAFE_COMMAND_WORKFLOW = """\
id: validate_only
name: "Validate Only"
type: closed_loop
version: "0.1.0"
goal:
  description: Run local validation.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review local validation.
steps:
  - id: validate
    command: pcl validate
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

PROJECT_COMMAND_WORKFLOW = """\
id: lint_review
name: "Lint Review"
type: closed_loop
version: "0.1.0"
goal:
  description: Run project lint command.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review local lint.
steps:
  - id: lint
    command: project.commands.lint
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

ROOT_OVERRIDE_WORKFLOW = """\
id: root_override
name: "Root Override"
type: closed_loop
version: "0.1.0"
goal:
  description: Try to validate another root.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review local validation.
steps:
  - id: validate_other
    command: pcl validate --root /tmp/other-project
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

UNSAFE_TEMPLATE = """\
id: unsafe_review
name: "Unsafe Review"
type: closed_loop
version: "0.1.0"
goal:
  description: Try an unsafe command.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review local validation.
steps:
  - id: destroy
    command: rm -rf .project-loop/project.db
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

BLOCKED_ONLY_WORKFLOW = """\
id: blocked_only
name: "Blocked Only"
type: closed_loop
version: "0.1.0"
goal:
  description: Try a sandbox-blocked pcl command.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review blocked command handling.
steps:
  - id: mutate
    command: pcl feature add
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_workflow_sandbox_template_dry_run_reports_safe_and_blocked_commands(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "sandbox", "--template", "feature_coverage", "--json"]) == 0
    payload = _json_output(capsys)
    sandbox = payload["sandbox"]

    assert payload["ok"] is True
    assert sandbox["contract_version"] == "workflow-sandbox/v1"
    assert sandbox["execute"] is False
    assert sandbox["target_type"] == "workflow_template"
    assert sandbox["workflow_id"] == "feature_coverage"
    assert sandbox["command_count"] == 3
    assert sandbox["safe_command_count"] == 2
    assert sandbox["blocked_command_count"] == 1
    commands = {command["raw_command"]: command for command in sandbox["commands"]}
    assert commands["pcl validate"]["safe_to_run"] is True
    assert commands["pcl render"]["safe_to_run"] is True
    assert commands["pcl feature add"]["safe_to_run"] is False
    assert commands["pcl feature add"]["blocked_reason"] == "pcl command is not sandbox-allowlisted: feature"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_sandbox_executed'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_workflow_sandbox_execute_runs_safe_commands_and_records_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "sandbox",
        "--template",
        "feature_coverage",
        "--execute",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    sandbox = payload["sandbox"]

    assert payload["ok"] is True
    assert sandbox["execute"] is True
    assert sandbox["executed_count"] == 2
    assert sandbox["skipped_count"] == 1
    assert sandbox["failed_count"] == 0
    assert sandbox["evidence_id"] == "E-0001"
    assert sandbox["evidence_path"] == ".project-loop/evidence/workflow-sandbox/E-0001/result.json"
    assert (tmp_path / sandbox["evidence_path"]).exists()
    assert (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").exists()
    statuses = {command["raw_command"]: command["status"] for command in sandbox["commands"]}
    assert statuses == {
        "pcl feature add": "skipped",
        "pcl render": "passed",
        "pcl validate": "passed",
    }

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        evidence = conn.execute(
            "SELECT id, type, path FROM evidence WHERE type = 'workflow_sandbox_run'"
        ).fetchone()
        event = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'workflow_sandbox_executed'"
        ).fetchone()
    finally:
        conn.close()
    assert dict(evidence) == {
        "id": "E-0001",
        "type": "workflow_sandbox_run",
        "path": ".project-loop/evidence/workflow-sandbox/E-0001/result.json",
    }
    event_payload = json.loads(event["payload_json"])
    assert event_payload["evidence_id"] == "E-0001"
    assert event_payload["executed_count"] == 2
    assert event_payload["skipped_count"] == 1
    assert event_payload["ok"] is True


def test_workflow_sandbox_execute_refuses_proposal_target(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "workflow.yaml").write_text(SAFE_COMMAND_WORKFLOW, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "workflow.yaml"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "sandbox",
        "--proposal",
        "WP-0001",
        "--execute",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "only allowed for approved workflow templates" in payload["error"]["message"]


def test_workflow_sandbox_blocks_unsafe_project_command(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("lint: \"\"", "lint: \"bash -c 'echo hi'\""),
        encoding="utf-8",
    )
    (tmp_path / "workflow.yaml").write_text(PROJECT_COMMAND_WORKFLOW, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "workflow.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approve local lint workflow",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "sandbox", "--template", "lint_review", "--json"]) == 0
    payload = _json_output(capsys)
    command = payload["sandbox"]["commands"][0]
    assert command["kind"] == "project_command"
    assert command["resolved_command"] == "bash -c 'echo hi'"
    assert command["safe_to_run"] is False
    assert command["blocked_reason"] == "project command executable is blocked: bash"
    assert payload["sandbox"]["safe_to_execute"] is False


def test_workflow_sandbox_verifier_failure_prevents_execution(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / ".project-loop" / "workflows" / "unsafe_review.yaml").write_text(
        UNSAFE_TEMPLATE,
        encoding="utf-8",
    )
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "sandbox",
        "--template",
        "unsafe_review",
        "--execute",
        "--json",
    ]) == 1
    payload = _json_output(capsys)
    sandbox = payload["sandbox"]
    assert payload["ok"] is False
    assert sandbox["verification"]["ok"] is False
    assert sandbox["executed_count"] == 0
    assert sandbox["evidence_id"] == ""
    assert any("forbidden fragment: rm -rf" in error for error in sandbox["verification"]["errors"])


def test_workflow_sandbox_execute_reports_noop_when_all_commands_blocked(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "workflow.yaml").write_text(BLOCKED_ONLY_WORKFLOW, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "workflow.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approve blocked-only workflow",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "sandbox",
        "--template",
        "blocked_only",
        "--execute",
        "--json",
    ]) == 1
    payload = _json_output(capsys)
    sandbox = payload["sandbox"]
    assert payload["ok"] is False
    assert sandbox["verification"]["ok"] is True
    assert sandbox["safe_to_execute"] is False
    assert sandbox["safe_command_count"] == 0
    assert sandbox["blocked_command_count"] == 1
    assert sandbox["executed_count"] == 0
    assert sandbox["skipped_count"] == 1
    assert sandbox["failed_count"] == 0
    assert sandbox["evidence_id"] == ""
    command = sandbox["commands"][0]
    assert command["status"] == "skipped"
    assert command["blocked_reason"] == "pcl command is not sandbox-allowlisted: feature"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        evidence_count = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE type = 'workflow_sandbox_run'"
        ).fetchone()["n"]
        event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_sandbox_executed'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert evidence_count == 0
    assert event_count == 0


def test_workflow_sandbox_blocks_pcl_root_override(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    (tmp_path / "workflow.yaml").write_text(ROOT_OVERRIDE_WORKFLOW, encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "workflow", "sandbox", "--file", "workflow.yaml", "--json"]) == 0
    payload = _json_output(capsys)
    command = payload["sandbox"]["commands"][0]
    assert command["safe_to_run"] is False
    assert command["blocked_reason"] == "pcl command flag is controlled by the sandbox: --root"
