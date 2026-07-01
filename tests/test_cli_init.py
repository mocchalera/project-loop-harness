from __future__ import annotations

import csv
import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_init_validate_render(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert (tmp_path / ".project-loop" / "project.db").exists()
    assert (tmp_path / "pcl.yaml").exists()
    assert (tmp_path / ".agents" / "skills" / "project-control-loop" / "SKILL.md").exists()
    assert main(["--root", str(tmp_path), "validate"]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0
    assert (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").exists()


def test_render_is_deterministic_for_unchanged_state(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0

    assert main(["--root", str(tmp_path), "render"]) == 0
    capsys.readouterr()
    html_path = tmp_path / ".project-loop" / "dashboard" / "dashboard.html"
    data_path = tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"
    first_html = html_path.read_text(encoding="utf-8")
    first_data = data_path.read_text(encoding="utf-8")

    assert main(["--root", str(tmp_path), "render"]) == 0
    assert html_path.read_text(encoding="utf-8") == first_html
    assert data_path.read_text(encoding="utf-8") == first_data


def test_feature_goal_defect_flow(tmp_path: Path) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Error message",
        "--actual",
        "Blank page",
    ]) == 0
    assert main(["--root", str(tmp_path), "render"]) == 0
    html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
    assert "Login" in html
    assert "Blank page" in html


def test_init_is_idempotent(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    payload = _json_output(capsys)

    assert payload == {
        "created": False,
        "event_appended": False,
        "ok": True,
        "root": str(tmp_path),
    }
    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 2
    assert "migration_applied" in events[0]
    assert "project_initialized" in events[1]

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert agents.count("<!-- project-loop-harness:start -->") == 1
    assert claude.count("<!-- project-loop-harness:start -->") == 1


def test_json_outputs_for_current_commands(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    assert _json_output(capsys)["created"] is True

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "Login",
        "--surface",
        "ui:/login",
        "--json",
    ]) == 0
    assert _json_output(capsys)["id"] == "F-0001"

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "create",
        "--title",
        "Coverage",
        "--json",
    ]) == 0
    assert _json_output(capsys)["id"] == "G-0001"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Error message",
        "--actual",
        "Blank page",
        "--json",
    ]) == 0
    assert _json_output(capsys)["id"] == "D-0001"

    assert main(["--root", str(tmp_path), "loop", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["open_defects"][0]["id"] == "D-0001"

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "triage_defect"

    assert main(["--root", str(tmp_path), "export", "csv", "--json"]) == 0
    exported = _json_output(capsys)
    assert exported["ok"] is True
    assert str(tmp_path / ".project-loop" / "exports" / "features.csv") in exported["paths"]

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    rendered = _json_output(capsys)
    assert rendered == {
        "data_path": str(tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"),
        "ok": True,
        "path": str(tmp_path / ".project-loop" / "dashboard" / "dashboard.html"),
    }


def test_export_csv_includes_reviewable_loop_state(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "Export",
        "--surface",
        "cli:pcl export csv",
    ]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Export review"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0

    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Export map\n\n## Findings\n\n- Export coverage reviewed.\n\n## Evidence\n\n- tests/test_cli_init.py\n",
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "ingest-agent-run", str(output_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--target-job",
        "J-0001",
        "--result",
        "approved",
        "--reason",
        "Export evidence accepted",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--run",
        "WR-0001",
        "--severity",
        "low",
        "--question",
        "Should CSV export include human queues?",
        "--recommendation",
        "Yes",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Include all reviewable state?",
        "--recommendation",
        "Include it",
        "--escalation",
        "ESC-0001",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "export", "csv", "--json"]) == 0
    exported = _json_output(capsys)

    expected_names = [
        "metadata.csv",
        "schema_migrations.csv",
        "events.csv",
        "goals.csv",
        "workflows.csv",
        "workflow_runs.csv",
        "agent_jobs.csv",
        "features.csv",
        "user_stories.csv",
        "test_cases.csv",
        "evidence.csv",
        "defects.csv",
        "decisions.csv",
        "verifications.csv",
        "escalations.csv",
        "workflow_proposals.csv",
    ]
    assert exported["paths"] == [
        str(tmp_path / ".project-loop" / "exports" / name) for name in expected_names
    ]

    exports_dir = tmp_path / ".project-loop" / "exports"
    assert _csv_rows(exports_dir / "workflow_runs.csv")[0]["id"] == "WR-0001"
    assert _csv_rows(exports_dir / "agent_jobs.csv")[0]["id"] == "J-0001"
    assert _csv_rows(exports_dir / "evidence.csv")[0]["id"] == "E-0001"
    assert _csv_rows(exports_dir / "verifications.csv")[0]["id"] == "V-0001"
    assert _csv_rows(exports_dir / "escalations.csv")[0]["id"] == "ESC-0001"
    assert _csv_rows(exports_dir / "decisions.csv")[0]["id"] == "DEC-0001"
    event_rows = _csv_rows(exports_dir / "events.csv")
    assert event_rows[0]["event_type"] == "migration_applied"
    assert any(row["event_type"] == "agent_output_ingested" for row in event_rows)
    assert (exports_dir / "workflow_proposals.csv").read_text(encoding="utf-8").startswith(
        "id,workflow_id,path,workflow_path,status,summary,review_summary,created_at,reviewed_at,"
    )


def test_state_command_before_init_fails_without_creating_loop_dir(tmp_path: Path, capsys) -> None:
    code = main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"])

    captured = capsys.readouterr()
    assert code == 3
    assert "not initialized" in captured.err
    assert not (tmp_path / ".project-loop").exists()


def test_state_command_before_init_can_emit_json_error(tmp_path: Path, capsys) -> None:
    code = main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login", "--json"])

    assert code == 3
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_initialized"


def test_defect_open_unknown_feature_returns_usage_error(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    code = main([
        "--root",
        str(tmp_path),
        "defect",
        "open",
        "--feature",
        "F-9999",
        "--severity",
        "high",
        "--expected",
        "Error message",
        "--actual",
        "Blank page",
    ])

    captured = capsys.readouterr()
    assert code == 2
    assert "Feature does not exist: F-9999" in captured.err


def test_goal_create_rejects_invalid_json(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    code = main([
        "--root",
        str(tmp_path),
        "goal",
        "create",
        "--title",
        "Coverage",
        "--completion-json",
        "{bad",
        "--json",
    ])

    assert code == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "completion-json must be valid JSON" in payload["error"]["message"]


def test_loop_run_requires_init(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--json"]) == 3
    assert _json_output(capsys)["error"]["code"] == "not_initialized"
