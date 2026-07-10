from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init_feature_defect(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
    assert main([
        "--root",
        str(root),
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
    capsys.readouterr()


def _db_rows(root: Path, sql: str) -> list[dict]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return [dict(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def test_defect_lifecycle_closes_with_evidence_and_updates_feature(tmp_path: Path, capsys) -> None:
    _init_feature_defect(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "triage_defect"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "triage",
        "D-0001",
        "--summary",
        "High impact login blank page",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "triaged"

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "start_defect"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "start",
        "D-0001",
        "--summary",
        "Begin login repair",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "in_progress"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "fix",
        "D-0001",
        "--summary",
        "Guarded login render path",
        "--evidence",
        "commit abc123 and pytest tests/test_login.py passed",
        "--json",
    ]) == 0
    fixed = _json_output(capsys)
    assert fixed["status"] == "fixed"
    assert fixed["evidence_id"] == "E-0001"

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "defect_repair",
        "--defect",
        "D-0001",
        "--json",
    ]) == 0
    run = _json_output(capsys)
    assert run["workflow_run"]["id"] == "WR-0001"
    assert run["workflow_run"]["defect_id"] == "D-0001"

    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
            "--json",
        ]) == 0
        assert _json_output(capsys)["status"] == "passed"

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "Login regression test passed",
        "--json",
    ]) == 0
    verification = _json_output(capsys)
    assert verification["id"] == "V-0001"

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Defect repair workflow passed",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "passed"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "verify",
        "D-0001",
        "--summary",
        "Approved verification ties to defect repair workflow",
        "--verification",
        "V-0001",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "verified"

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "close_defect"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "close",
        "D-0001",
        "--summary",
        "Login defect closed",
        "--evidence",
        "V-0001 approved and dashboard reviewed",
        "--json",
    ]) == 0
    closed = _json_output(capsys)
    assert closed["status"] == "closed"
    assert closed["feature_status"] == "passing"

    assert _db_rows(tmp_path, "SELECT id, status FROM defects") == [{"id": "D-0001", "status": "closed"}]
    assert _db_rows(tmp_path, "SELECT id, status FROM features") == [{"id": "F-0001", "status": "passing"}]
    assert _db_rows(tmp_path, "SELECT id, type FROM evidence ORDER BY id") == [
        {"id": "E-0001", "type": "defect_fix"},
        {"id": "E-0002", "type": "defect_close"},
    ]

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "idle"

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "defect_triaged" in events
    assert "defect_started" in events
    assert "defect_fixed" in events
    assert "defect_verified" in events
    assert "defect_closed" in events
    assert "feature_status_updated" in events


def test_defect_waive_updates_feature_and_dashboard_count(tmp_path: Path, capsys) -> None:
    _init_feature_defect(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "waive",
        "D-0001",
        "--reason",
        "Known browser limitation accepted by product owner",
        "--json",
    ]) == 0
    waived = _json_output(capsys)
    assert waived["status"] == "waived"
    assert waived["feature_status"] == "waived"

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = json.loads((tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    assert data["counts"]["open_defects"] == 0

    assert main(["--root", str(tmp_path), "loop", "status", "--json"]) == 0
    assert _json_output(capsys)["open_defects"] == []


def test_defect_lifecycle_rejects_invalid_transitions(tmp_path: Path, capsys) -> None:
    _init_feature_defect(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "fix",
        "D-0001",
        "--summary",
        "Too early",
        "--evidence",
        "none",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot transition from status open" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "triage",
        "D-0001",
        "--summary",
        "Triaged",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "start",
        "D-0001",
        "--summary",
        "Started",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "fix",
        "D-0001",
        "--summary",
        "Missing evidence",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "--evidence is required" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "waive",
        "D-0001",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "--reason is required" in payload["error"]["message"]


def test_defect_verify_requires_approved_verification_tied_to_defect(tmp_path: Path, capsys) -> None:
    _init_feature_defect(tmp_path, capsys)
    for command in [
        ["defect", "triage", "D-0001", "--summary", "Triaged"],
        ["defect", "start", "D-0001", "--summary", "Started"],
        [
            "defect",
            "fix",
            "D-0001",
            "--summary",
            "Fixed",
            "--evidence",
            "Fix evidence",
        ],
    ]:
        assert main(["--root", str(tmp_path), *command]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Unrelated"]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
        "--json",
    ]) == 0
    _json_output(capsys)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "Unrelated verification",
        "--json",
    ]) == 0
    assert _json_output(capsys)["id"] == "V-0001"

    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "verify",
        "D-0001",
        "--summary",
        "Should fail",
        "--verification",
        "V-0001",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "is not tied to defect D-0001" in payload["error"]["message"]
