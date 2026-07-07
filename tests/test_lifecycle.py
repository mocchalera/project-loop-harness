from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_run(root: Path, capsys) -> dict:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(root),
        "loop",
        "run",
        "feature_coverage",
        "--goal",
        "G-0001",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    return result


def _db_rows(root: Path, sql: str) -> list[dict]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return [dict(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _audit_counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "events": int(conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]),
            "events_jsonl": len((root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()),
            "evidence": int(conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]),
        }
    finally:
        conn.close()


def _event_payloads(root: Path, event_type: str) -> list[dict]:
    events = []
    for line in (root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["event_type"] == event_type:
            events.append(event["payload"])
    return events


def _valid_rubric(evidence_id: str | None = None) -> dict:
    return {
        "contract_version": "rubric/v1",
        "acceptance_criteria": [
            {"criterion": "Expected behavior was verified", "met": "yes", "evidence_id": evidence_id}
        ],
        "regression_risk": {"level": "low", "notes": None},
        "test_evidence": [
            {"evidence_id": evidence_id, "command": "pytest", "summary": "Focused tests passed"}
        ]
        if evidence_id
        else [],
        "security_ux_checks": [{"check": "No secrets emitted", "result": "pass", "notes": None}],
        "confidence_score": 0.9,
        "evidence_completeness": "complete",
    }


def _create_test_evidence(root: Path, capsys) -> None:
    assert main(["--root", str(root), "feature", "add", "--name", "Rubric", "--surface", "cli:pcl"]) == 0
    assert main([
        "--root",
        str(root),
        "test",
        "plan",
        "--feature",
        "F-0001",
        "--type",
        "acceptance",
        "--scenario",
        "Record a structured rubric",
        "--expected",
        "The rubric is stored with evidence references",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Rubric path passed",
        "--evidence",
        "pytest tests/test_rubric.py passed",
        "--run",
        "WR-0001",
    ]) == 0
    capsys.readouterr()


def test_lifecycle_completes_run_and_closes_goal(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Mapped the surface.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Mapped project surfaces",
        "--output",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--json",
    ]) == 0
    completed_job = _json_output(capsys)
    assert completed_job["status"] == "passed"
    assert completed_job["workflow_started"] is True

    for job_id, summary in [
        ("J-0002", "Wrote user stories"),
        ("J-0003", "Designed tests"),
    ]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "complete",
            job_id,
            "--summary",
            summary,
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
        "pytest passed",
        "--reason",
        "dashboard rendered",
        "--json",
    ]) == 0
    verification = _json_output(capsys)
    assert verification["id"] == "V-0001"
    assert verification["result"] == "approved"

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Feature coverage complete",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "passed"

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Coverage goal done",
        "--verification",
        "V-0001",
        "--json",
    ]) == 0
    closed = _json_output(capsys)
    assert closed["status"] == "closed"
    assert closed["changed"] is True

    before_no_op = _audit_counts(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Already closed",
        "--json",
    ]) == 0
    no_op = _json_output(capsys)
    assert no_op == {
        "changed": False,
        "evidence_recorded": False,
        "goal_id": "G-0001",
        "ok": True,
        "status": "closed",
    }
    assert _audit_counts(tmp_path) == before_no_op

    for _ in range(2):
        assert main([
            "--root",
            str(tmp_path),
            "goal",
            "close",
            "G-0001",
            "--summary",
            "Still closed",
            "--json",
        ]) == 0
        assert _json_output(capsys) == no_op
        assert _audit_counts(tmp_path) == before_no_op

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Already closed with evidence",
        "--evidence",
        "Do not record",
        "--json",
    ]) == 0
    with_evidence = _json_output(capsys)
    assert with_evidence["changed"] is False
    assert with_evidence["evidence_recorded"] is False
    assert _audit_counts(tmp_path) == before_no_op

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Already closed",
    ]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Goal G-0001 already closed; no change recorded.\n"
    assert _audit_counts(tmp_path) == before_no_op

    assert _db_rows(tmp_path, "SELECT id, status FROM agent_jobs ORDER BY id") == [
        {"id": "J-0001", "status": "passed"},
        {"id": "J-0002", "status": "passed"},
        {"id": "J-0003", "status": "passed"},
    ]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "passed"}
    ]
    goal = _db_rows(tmp_path, "SELECT id, status, completion_json FROM goals")[0]
    assert goal["id"] == "G-0001"
    assert goal["status"] == "closed"
    assert json.loads(goal["completion_json"])["closure"]["verification_id"] == "V-0001"

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "agent_job_completed" in events
    assert "workflow_run_started" in events
    assert "verification_recorded" in events
    assert "workflow_run_completed" in events
    assert "goal_closed" in events

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    assert _json_output(capsys)["type"] == "create_goal"


def test_jobs_complete_with_evidence_regresses_ax1_empty_evidence_symptom(
    tmp_path: Path,
    capsys,
) -> None:
    _create_run(tmp_path, capsys)
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Mapped the surface.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )

    assert main([
        "--root",
        str(tmp_path),
        "evidence",
        "add",
        "--file",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--summary",
        "Mapper output artifact",
        "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    assert evidence["id"] == "E-0001"

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Mapped project surfaces",
        "--output",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
        "--evidence",
        "E-0001",
        "--json",
    ]) == 0
    completed = _json_output(capsys)
    assert completed["status"] == "passed"
    assert completed["evidence_id"] == "E-0001"
    assert completed["latest_evidence_id"] == "E-0001"

    completion_payloads = _event_payloads(tmp_path, "agent_job_completed")
    assert completion_payloads[-1]["evidence_id"] == "E-0001"

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    read_job = _json_output(capsys)["job"]
    assert read_job["output_path"] == ".project-loop/evidence/agent-runs/J-0001/output.md"
    assert read_job["evidence_ids"] == ["E-0001"]
    assert read_job["latest_evidence_id"] == "E-0001"
    assert read_job["latest_evidence_path"] == ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json"

    assert main(["--root", str(tmp_path), "jobs", "list", "--json"]) == 0
    listed_job = _json_output(capsys)["jobs"][0]
    assert listed_job["evidence_ids"] == ["E-0001"]
    assert listed_job["latest_evidence_id"] == "E-0001"

    assert main(["--root", str(tmp_path), "render"]) == 0
    capsys.readouterr()
    dashboard_data = json.loads(
        (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
    dashboard_job = dashboard_data["agent_jobs"][0]
    assert dashboard_job["evidence_ids"] == ["E-0001"]
    assert dashboard_job["latest_evidence_id"] == "E-0001"
    assert dashboard_job["latest_evidence_path"] == ".project-loop/evidence/adhoc/e-0001-adhoc-v0.json"

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}


def test_jobs_complete_rejects_unknown_evidence_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _create_run(tmp_path, capsys)
    before = _audit_counts(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Mapped project surfaces",
        "--evidence",
        "E-9999",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "job_completion_missing_evidence"
    assert payload["error"]["details"] == {"evidence_id": "E-9999"}
    assert _audit_counts(tmp_path) == before
    assert _db_rows(
        tmp_path,
        "SELECT id, status, output_path, summary FROM agent_jobs WHERE id = 'J-0001'",
    ) == [{"id": "J-0001", "status": "queued", "output_path": None, "summary": "step:map_surfaces"}]
    assert _event_payloads(tmp_path, "agent_job_completed") == []


def test_jobs_complete_without_evidence_keeps_existing_completion_shape(
    tmp_path: Path,
    capsys,
) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Mapped project surfaces",
        "--json",
    ]) == 0
    completed = _json_output(capsys)
    assert "evidence_id" not in completed
    assert "latest_evidence_id" not in completed

    completion_payloads = _event_payloads(tmp_path, "agent_job_completed")
    assert "evidence_id" not in completion_payloads[-1]

    assert main(["--root", str(tmp_path), "jobs", "read", "J-0001", "--json"]) == 0
    read_job = _json_output(capsys)["job"]
    assert read_job["status"] == "passed"
    assert read_job["evidence_ids"] == []
    assert read_job["evidence"] == []
    assert read_job["latest_evidence_id"] is None
    assert read_job["latest_evidence_path"] is None


def test_verification_record_accepts_rubric_v1_inline_and_file(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _create_test_evidence(tmp_path, capsys)
    rubric = _valid_rubric("E-0001")
    rubric_path = tmp_path / "rubric.json"
    rubric_path.write_text(json.dumps(rubric), encoding="utf-8")

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--rubric-file",
        str(rubric_path),
        "--reason",
        "Structured file rubric passed",
        "--json",
    ]) == 0
    file_record = _json_output(capsys)
    assert file_record["id"] == "V-0001"
    assert file_record["rubric_contract_version"] == "rubric/v1"

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--rubric-json",
        json.dumps(rubric),
        "--reason",
        "Structured inline rubric passed",
        "--json",
    ]) == 0
    inline_record = _json_output(capsys)
    assert inline_record["id"] == "V-0002"
    assert inline_record["rubric_contract_version"] == "rubric/v1"

    rows = _db_rows(tmp_path, "SELECT id, rubric_json FROM verifications ORDER BY id")
    assert [row["id"] for row in rows] == ["V-0001", "V-0002"]
    assert json.loads(rows[0]["rubric_json"])["contract_version"] == "rubric/v1"

    payloads = _event_payloads(tmp_path, "verification_recorded")
    assert [payload["rubric_contract_version"] for payload in payloads] == ["rubric/v1", "rubric/v1"]


def test_verification_record_rejects_invalid_rubric_v1(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    rubric = _valid_rubric()
    del rubric["acceptance_criteria"]

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--rubric-json",
        json.dumps(rubric),
        "--reason",
        "Invalid rubric should fail",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "rubric/v1" in payload["error"]["message"]
    assert "acceptance_criteria is required." in payload["error"]["details"]["errors"]
    assert _db_rows(tmp_path, "SELECT id FROM verifications") == []
    assert _event_payloads(tmp_path, "verification_recorded") == []


def test_verification_record_rejects_missing_rubric_evidence_id(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--rubric-json",
        json.dumps(_valid_rubric("E-9999")),
        "--reason",
        "Missing evidence should fail",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["missing_evidence_ids"] == ["E-9999"]
    assert _db_rows(tmp_path, "SELECT id FROM verifications") == []
    assert _event_payloads(tmp_path, "verification_recorded") == []


def test_verification_record_keeps_free_form_rubric_compatibility(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    free_form = {
        "contract_version": "legacy/v1",
        "acceptance_criteria": [{"evidence_id": "E-9999"}],
        "notes": "Legacy rubric shape remains accepted.",
    }

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "inconclusive",
        "--rubric-json",
        json.dumps(free_form),
        "--reason",
        "Legacy rubric accepted",
        "--json",
    ]) == 0
    payload = _json_output(capsys)
    assert payload["id"] == "V-0001"
    assert payload["rubric_contract_version"] is None
    assert _event_payloads(tmp_path, "verification_recorded")[0]["rubric_contract_version"] is None


def test_verification_list_and_read_are_read_only_and_ordered(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--rubric-json",
        json.dumps(_valid_rubric()),
        "--reason",
        "Approved with structured rubric",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "rejected",
        "--rubric-json",
        '{"legacy": true}',
        "--reason",
        "Rejected with free-form rubric",
    ]) == 0
    capsys.readouterr()
    events_before = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")

    assert main(["--root", str(tmp_path), "verification", "list", "--json"]) == 0
    listed = _json_output(capsys)
    assert [item["id"] for item in listed["verifications"]] == ["V-0001", "V-0002"]
    assert [item["result"] for item in listed["verifications"]] == ["approved", "rejected"]

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "list",
        "--run",
        "WR-0001",
        "--result",
        "rejected",
        "--json",
    ]) == 0
    filtered = _json_output(capsys)
    assert [item["id"] for item in filtered["verifications"]] == ["V-0002"]

    assert main(["--root", str(tmp_path), "verification", "read", "V-0001", "--json"]) == 0
    read = _json_output(capsys)
    verification = read["verification"]
    assert verification["id"] == "V-0001"
    assert verification["rubric"]["contract_version"] == "rubric/v1"
    assert verification["rubric_contract_version"] == "rubric/v1"
    assert verification["reasons"] == ["Approved with structured rubric"]

    events_after = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert events_after == events_before


def test_next_prioritizes_active_workflow_lifecycle(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "continue_workflow"
    assert action["command"] == "pcl jobs read J-0001"

    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(tmp_path),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "record_verification"
    assert action["command"].startswith("pcl verification record --run WR-0001")

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
        "Manual verification passed",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "complete_workflow"
    assert action["command"].startswith("pcl loop complete WR-0001")


def test_cancel_workflow_cancels_active_jobs_and_goal_can_cancel(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "Superseded by newer run",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["status"] == "cancelled"
    assert result["cancelled_jobs"] == ["J-0001", "J-0002", "J-0003"]

    assert _db_rows(tmp_path, "SELECT DISTINCT status FROM agent_jobs") == [{"status": "cancelled"}]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "cancelled"}
    ]

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "cancel",
        "G-0001",
        "--summary",
        "No longer needed",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "cancelled"

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "workflow_run_cancelled" in events
    assert events.count("agent_job_cancelled") == 3
    assert "goal_cancelled" in events


def test_fail_workflow_cancels_active_jobs(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "fail",
        "WR-0001",
        "--summary",
        "Project command failed",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["status"] == "failed"
    assert result["cancelled_jobs"] == ["J-0001", "J-0002", "J-0003"]

    assert _db_rows(tmp_path, "SELECT DISTINCT status FROM agent_jobs") == [{"status": "cancelled"}]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "failed"}
    ]

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "workflow_run_failed" in events
    assert events.count("agent_job_cancelled") == 3


def test_fail_job_cancels_sibling_active_jobs(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "fail",
        "J-0001",
        "--summary",
        "Mapper failed",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result["status"] == "failed"
    assert result["cancelled_jobs"] == ["J-0002", "J-0003"]

    assert _db_rows(tmp_path, "SELECT id, status FROM agent_jobs ORDER BY id") == [
        {"id": "J-0001", "status": "failed"},
        {"id": "J-0002", "status": "cancelled"},
        {"id": "J-0003", "status": "cancelled"},
    ]
    assert _db_rows(tmp_path, "SELECT id, status FROM workflow_runs") == [
        {"id": "WR-0001", "status": "failed"}
    ]

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "agent_job_failed" in events
    assert "workflow_run_failed" in events
    assert events.count("agent_job_cancelled") == 2


def test_lifecycle_rejects_invalid_transitions(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Too early",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be completed until every job has passed" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Too early",
        "--evidence",
        "none",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be closed while workflow runs are active" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "loop",
        "cancel",
        "WR-0001",
        "--summary",
        "Stop run",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Missing evidence",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "requires --evidence or --verification" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-9999",
        "--summary",
        "Unknown goal",
        "--evidence",
        "unknown",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"] == {"goal_id": "G-9999"}

    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Cancelled goal", "--json"]) == 0
    assert _json_output(capsys)["id"] == "G-0002"
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "cancel",
        "G-0002",
        "--summary",
        "No longer needed",
        "--json",
    ]) == 0
    cancelled = _json_output(capsys)
    assert cancelled["status"] == "cancelled"
    assert cancelled["changed"] is True
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0002",
        "--summary",
        "Wrong terminal state",
        "--evidence",
        "should still fail",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"] == {"goal_id": "G-0002", "status": "cancelled"}

    assert main([
        "--root",
        str(tmp_path),
        "jobs",
        "complete",
        "J-0001",
        "--summary",
        "Already cancelled",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot transition from status cancelled" in payload["error"]["message"]
