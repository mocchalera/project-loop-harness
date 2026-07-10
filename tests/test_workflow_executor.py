from __future__ import annotations

import json
from pathlib import Path
import sys

from pcl import workflows
from pcl.cli import main
from pcl.db import connect
from pcl.errors import InvalidInputError


COMMAND_ONLY_WORKFLOW = """\
id: validate_auto
name: "Validate Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Run validation automatically.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review validation.
steps:
  - id: validate
    command: pcl validate
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

AGENT_ONLY_WORKFLOW = """\
id: agent_auto
name: "Agent Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Run one agent automatically.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review the prompt.
steps:
  - id: review
    agent: reviewer
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

FAILING_PROJECT_COMMAND_WORKFLOW = """\
id: failing_test_auto
name: "Failing Test Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Run a failing project command.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review failing command.
steps:
  - id: test
    command: project.commands.test
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

COMMAND_THEN_AGENT_WORKFLOW = """\
id: command_then_agent_auto
name: "Command Then Agent Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Run command before agent.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review after command.
steps:
  - id: test
    command: project.commands.test
  - id: review
    agent: reviewer
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""

RULES_ONLY_WORKFLOW = """\
id: rules_only_auto
name: "Rules Only Auto"
type: closed_loop
version: "0.1.0"
goal:
  description: Try a rules-only workflow.
  completion: []
agents:
  reviewer:
    mode: read_only
    purpose: Review rules.
steps:
  - id: decide
    rules:
      - if: verification.result == approved
        then: complete
budget:
  max_iterations: 1
stop_conditions:
  - human approval required
"""


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _approve_workflow(tmp_path: Path, capsys, workflow_text: str) -> None:
    source = tmp_path / "workflow.yaml"
    source.write_text(workflow_text, encoding="utf-8")
    assert main(["--root", str(tmp_path), "workflow", "propose", "--file", "workflow.yaml"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "workflow",
        "proposals",
        "approve",
        "WP-0001",
        "--summary",
        "Approve for executor test",
    ]) == 0
    capsys.readouterr()


def test_loop_execute_command_only_workflow_completes_and_records_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, COMMAND_ONLY_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "validate_auto", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["contract_version"] == "workflow-executor/v1"
    assert payload["status"] == "passed"
    assert payload["workflow_run_id"] == "WR-0001"
    assert payload["evidence_id"] == "E-0001"
    assert payload["verification_id"] == "V-0001"
    assert payload["completion"]["status"] == "passed"
    assert payload["rendered"] is True
    assert payload["dashboard_data_path"] == str(tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json")
    assert "dashboard_path" not in payload
    assert str(tmp_path / ".project-loop" / "dashboard" / "dashboard.html") not in json.dumps(payload)
    assert payload["steps"][0]["kind"] == "command"
    assert payload["steps"][0]["status"] == "passed"
    assert (tmp_path / payload["evidence_path"]).exists()

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run = conn.execute("SELECT status FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
        evidence = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?",
            (payload["evidence_id"],),
        ).fetchone()
        events = [
            row["event_type"]
            for row in conn.execute(
                "SELECT event_type FROM events WHERE entity_id = 'WR-0001' ORDER BY rowid"
            ).fetchall()
        ]
        evidence_event_outbox = conn.execute(
            """
            SELECT outbox_records.status
            FROM events
            JOIN outbox_records ON outbox_records.event_id = events.id
            WHERE events.event_type = 'workflow_execution_evidence_recorded'
              AND events.entity_id = 'WR-0001'
            """
        ).fetchone()
    finally:
        conn.close()
    assert run["status"] == "passed"
    assert dict(evidence) == {
        "type": "workflow_execution",
        "path": ".project-loop/evidence/workflow-executions/WR-0001/result.json",
    }
    assert "workflow_execution_started" in events
    assert "workflow_execution_evidence_recorded" in events
    assert "workflow_execution_finished" in events
    assert "workflow_run_completed" in events
    assert evidence_event_outbox["status"] == "delivered"


def test_loop_execute_bundled_executor_smoke_runs_in_fresh_project(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    workflow_path = tmp_path / ".project-loop" / "workflows" / "executor_smoke.yaml"
    assert workflow_path.exists()

    assert main(["--root", str(tmp_path), "workflow", "verify", "--template", "executor_smoke", "--json"]) == 0
    verification = _json_output(capsys)
    assert verification["ok"] is True
    assert verification["verification"]["errors"] == []

    assert main(["--root", str(tmp_path), "workflow", "sandbox", "--template", "executor_smoke", "--json"]) == 0
    sandbox = _json_output(capsys)["sandbox"]
    assert sandbox["blocked_command_count"] == 0
    assert sandbox["safe_command_count"] == 3

    assert main(["--root", str(tmp_path), "loop", "execute", "executor_smoke", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["ok"] is True
    assert payload["contract_version"] == "workflow-executor/v1"
    assert payload["workflow_id"] == "executor_smoke"
    assert payload["status"] == "passed"
    assert payload["evidence_id"] == "E-0001"
    assert payload["verification_id"] == "V-0001"
    assert payload["rendered"] is True
    assert payload["dashboard_data_path"] == str(tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json")
    assert "dashboard_path" not in payload
    assert str(tmp_path / ".project-loop" / "dashboard" / "dashboard.html") not in json.dumps(payload)
    assert [step["status"] for step in payload["steps"]] == ["passed", "passed", "passed"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True


def test_loop_execute_requires_explicit_agent_execution(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, AGENT_ONLY_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "agent_auto", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "requires --allow-agent-exec" in payload["error"]["message"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_loop_execute_no_auto_verify_requires_no_complete_before_run_creation(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, COMMAND_ONLY_WORKFLOW)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "execute",
        "validate_auto",
        "--no-auto-verify",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "--no-auto-verify requires --no-complete."

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        runs = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
        evidence = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE type = 'workflow_execution'"
        ).fetchone()["n"]
        events = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type LIKE 'workflow_execution_%'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert runs == 0
    assert evidence == 0
    assert events == 0


def test_loop_execute_generic_shell_agent_workflow_completes(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, AGENT_ONLY_WORKFLOW)
    agent_script = tmp_path / "agent.py"
    agent_script.write_text(
        "\n".join(
            [
                "import sys",
                "prompt = sys.stdin.read()",
                "print('# Automated agent result')",
                "print('')",
                "print('## Findings')",
                "print(f'- Prompt bytes: {len(prompt)}')",
                "print('')",
                "print('## Evidence')",
                "print('- Generated by local test agent.')",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PCL_AGENT_COMMAND", f"{sys.executable} {agent_script}")

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "execute",
        "agent_auto",
        "--agent-adapter",
        "generic_shell",
        "--allow-agent-exec",
        "--json",
    ]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["steps"][0]["kind"] == "agent"
    assert payload["steps"][0]["status"] == "passed"
    assert payload["steps"][0]["latest_evidence_id"] == "E-0001"
    assert payload["evidence_id"] == "E-0002"
    assert payload["verification_id"] == "V-0001"

    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    assert output_path.exists()
    assert "Automated agent result" in output_path.read_text(encoding="utf-8")

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        job = conn.execute("SELECT status, output_path FROM agent_jobs WHERE id = 'J-0001'").fetchone()
        run = conn.execute("SELECT status FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
    finally:
        conn.close()
    assert job["status"] == "passed"
    assert job["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert run["status"] == "passed"


def test_loop_execute_rejects_blocked_command_before_creating_run(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "loop", "execute", "feature_coverage", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "blocked by the guarded executor" in payload["error"]["message"]
    assert payload["error"]["details"]["blocked_commands"][0]["raw_command"] == "pcl feature add"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_loop_execute_rejects_workflow_with_no_executable_steps_before_creating_run(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, RULES_ONLY_WORKFLOW)

    assert main(["--root", str(tmp_path), "workflow", "verify", "--template", "rules_only_auto", "--json"]) == 0
    verification = _json_output(capsys)
    assert verification["ok"] is True

    assert main(["--root", str(tmp_path), "loop", "execute", "rules_only_auto", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "Workflow rules_only_auto has no executable command or agent steps."
    assert payload["error"]["details"] == {
        "agent_step_count": 0,
        "command_count": 0,
        "workflow_id": "rules_only_auto",
    }

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_loop_execute_failed_command_marks_run_failed(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("test: \"\"", "test: \"python -m pytest missing_test_file.py\""),
        encoding="utf-8",
    )
    _approve_workflow(tmp_path, capsys, FAILING_PROJECT_COMMAND_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--json"]) == 1
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["steps"][0]["status"] == "failed"
    assert payload["evidence_id"] == "E-0001"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run = conn.execute("SELECT status, summary FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
    finally:
        conn.close()
    assert run["status"] == "failed"
    assert "Command step test failed" in run["summary"]


def test_loop_execute_missing_command_executable_records_failed_state(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("test: \"\"", "test: \"/tmp/pcl-missing-bin/pytest\""),
        encoding="utf-8",
    )
    _approve_workflow(tmp_path, capsys, FAILING_PROJECT_COMMAND_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--json"]) == 1
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["steps"][0]["status"] == "failed"
    assert payload["evidence_id"] == "E-0001"
    assert payload["failure_reason"] == "Command step test failed: project.commands.test"
    assert (tmp_path / payload["steps"][0]["stderr_path"]).read_text(encoding="utf-8").startswith(
        "FileNotFoundError:"
    )

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run = conn.execute("SELECT status, summary FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
        event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_execution_finished'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert run["status"] == "failed"
    assert "Command step test failed" in run["summary"]
    assert event_count == 1


def test_loop_execute_command_failure_cancels_unreached_agent_jobs(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("test: \"\"", "test: \"python -m pytest missing_test_file.py\""),
        encoding="utf-8",
    )
    _approve_workflow(tmp_path, capsys, COMMAND_THEN_AGENT_WORKFLOW)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "execute",
        "command_then_agent_auto",
        "--agent-adapter",
        "generic_shell",
        "--allow-agent-exec",
        "--json",
    ]) == 1
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["steps"][0]["kind"] == "command"
    assert payload["steps"][0]["status"] == "failed"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        job = conn.execute("SELECT status, summary FROM agent_jobs WHERE id = 'J-0001'").fetchone()
        run = conn.execute("SELECT status FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
        cancel_events = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'agent_job_cancelled'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert run["status"] == "failed"
    assert job["status"] == "cancelled"
    assert "Command step test failed" in job["summary"]
    assert cancel_events == 1


def test_loop_execute_retry_failed_run_creates_linked_new_run(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("test: \"\"", "test: \"python -m pytest missing_test_file.py\""),
        encoding="utf-8",
    )
    _approve_workflow(tmp_path, capsys, FAILING_PROJECT_COMMAND_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--json"]) == 1
    failed = _json_output(capsys)
    assert failed["workflow_run_id"] == "WR-0001"
    assert failed["status"] == "failed"

    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace(
            "test: \"python -m pytest missing_test_file.py\"",
            "test: \"python -m pytest --version\"",
        ),
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--retry", "WR-0001", "--json"]) == 0
    retry = _json_output(capsys)
    assert retry["ok"] is True
    assert retry["workflow_run_id"] == "WR-0002"
    assert retry["execution_mode"] == "retry"
    assert retry["retry_of_workflow_run_id"] == "WR-0001"
    assert retry["status"] == "passed"
    assert retry["evidence_id"] == "E-0002"
    assert retry["verification_id"] == "V-0001"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        runs = [
            dict(row)
            for row in conn.execute(
                "SELECT id, status, iteration FROM workflow_runs ORDER BY id"
            ).fetchall()
        ]
        event = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'workflow_execution_retried'"
        ).fetchone()
    finally:
        conn.close()
    assert runs == [
        {"id": "WR-0001", "status": "failed", "iteration": 1},
        {"id": "WR-0002", "status": "passed", "iteration": 2},
    ]
    assert json.loads(event["payload_json"])["retry_of_workflow_run_id"] == "WR-0001"

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--retry", "WR-0001", "--json"]) == 2
    repeated = _json_output(capsys)
    assert repeated["error"]["code"] == "invalid_input"
    assert repeated["error"]["details"]["retry_workflow_run_id"] == "WR-0002"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
        retry_event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_execution_retried'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert run_count == 2
    assert retry_event_count == 1

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "create_goal"


def test_loop_execute_retry_run_creation_and_link_event_are_atomic(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    pcl_yaml = tmp_path / "pcl.yaml"
    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace("test: \"\"", "test: \"python -m pytest missing_test_file.py\""),
        encoding="utf-8",
    )
    _approve_workflow(tmp_path, capsys, FAILING_PROJECT_COMMAND_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--json"]) == 1
    assert _json_output(capsys)["workflow_run_id"] == "WR-0001"

    pcl_yaml.write_text(
        pcl_yaml.read_text(encoding="utf-8").replace(
            "test: \"python -m pytest missing_test_file.py\"",
            "test: \"python -m pytest --version\"",
        ),
        encoding="utf-8",
    )
    original_append_event = workflows.append_event

    def fail_retry_event(**kwargs):
        if kwargs["event_type"] == "workflow_execution_retried":
            raise InvalidInputError("Injected retry link failure.")
        return original_append_event(**kwargs)

    monkeypatch.setattr(workflows, "append_event", fail_retry_event)

    assert main(["--root", str(tmp_path), "loop", "execute", "failing_test_auto", "--retry", "WR-0001", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "Injected retry link failure."

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        runs = [
            dict(row)
            for row in conn.execute(
                "SELECT id, status, iteration FROM workflow_runs ORDER BY id"
            ).fetchall()
        ]
        retry_event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_execution_retried'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert runs == [{"id": "WR-0001", "status": "failed", "iteration": 1}]
    assert retry_event_count == 0


def test_loop_execute_resume_existing_active_run_without_creating_new_run(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, COMMAND_ONLY_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "run", "validate_auto", "--json"]) == 0
    run = _json_output(capsys)["workflow_run"]
    assert run["id"] == "WR-0001"
    assert run["status"] == "queued"

    assert main(["--root", str(tmp_path), "loop", "execute", "validate_auto", "--resume", "WR-0001", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["ok"] is True
    assert payload["workflow_run_id"] == "WR-0001"
    assert payload["execution_mode"] == "resume"
    assert payload["resumed_from_workflow_run_id"] == "WR-0001"
    assert payload["status"] == "passed"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
        stored = conn.execute("SELECT status FROM workflow_runs WHERE id = 'WR-0001'").fetchone()
        resumed_events = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type = 'workflow_execution_resumed'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert run_count == 1
    assert stored["status"] == "passed"
    assert resumed_events == 1


def test_loop_execute_retry_rejects_passed_run(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    _approve_workflow(tmp_path, capsys, COMMAND_ONLY_WORKFLOW)

    assert main(["--root", str(tmp_path), "loop", "execute", "validate_auto", "--json"]) == 0
    assert _json_output(capsys)["workflow_run_id"] == "WR-0001"

    assert main(["--root", str(tmp_path), "loop", "execute", "validate_auto", "--retry", "WR-0001", "--json"]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be retried from status passed" in payload["error"]["message"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) AS n FROM workflow_runs").fetchone()["n"]
    finally:
        conn.close()
    assert run_count == 1
