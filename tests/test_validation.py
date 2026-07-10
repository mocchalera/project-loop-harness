from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect
from pcl.paths import resolve_paths
from pcl.validators import validate_project


def test_validate_missing_project_loop(tmp_path: Path) -> None:
    result = validate_project(resolve_paths(tmp_path))
    assert not result.ok
    assert "Missing .project-loop" in result.errors[0]


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _update_db(root: Path, sql: str, params: tuple = ()) -> None:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _insert_context_receipt_link(
    root: Path,
    *,
    evidence_id: str,
    link_target_type: str,
    link_target_id: str,
    link_role: str,
    binding_target_type: str,
    binding_target_id: str,
) -> None:
    receipt_path = f".project-loop/evidence/context-receipts/{evidence_id.lower()}-impact-v0.json"
    absolute_receipt_path = root / receipt_path
    absolute_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_receipt_path.write_text(
        json.dumps(
            {
                "contract_version": "context-receipt/v0",
                "evidence_id": evidence_id,
                "receipt_path": receipt_path,
                "target_binding": {
                    "target_type": binding_target_type,
                    "target_id": binding_target_id,
                    "binding_strength": "caller_asserted",
                    "source": "impact_flag",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _update_db(
        root,
        """
        INSERT INTO evidence(id, type, path, summary, created_at)
        VALUES (?, 'context_receipt', ?, 'Context receipt', '2026-07-08T00:00:00Z')
        """,
        (evidence_id, receipt_path),
    )
    _update_db(
        root,
        """
        INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
        VALUES (?, ?, ?, ?, '2026-07-08T00:00:00Z')
        """,
        (evidence_id, link_target_type, link_target_id, link_role),
    )


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


def _complete_all_jobs(root: Path, capsys, job_ids: list[str]) -> None:
    for job_id in job_ids:
        assert main([
            "--root",
            str(root),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    capsys.readouterr()


def _create_closed_defect(root: Path, capsys) -> None:
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
    assert main(["--root", str(root), "defect", "triage", "D-0001", "--summary", "Triaged"]) == 0
    assert main(["--root", str(root), "defect", "start", "D-0001", "--summary", "Started"]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "fix",
        "D-0001",
        "--summary",
        "Fixed",
        "--evidence",
        "commit abc123 and regression test passed",
    ]) == 0
    assert main(["--root", str(root), "loop", "run", "defect_repair", "--defect", "D-0001"]) == 0
    _complete_all_jobs(root, capsys, ["J-0001", "J-0002", "J-0003"])
    assert main([
        "--root",
        str(root),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "Defect repair verified",
    ]) == 0
    assert main(["--root", str(root), "loop", "complete", "WR-0001", "--summary", "Repair passed"]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "verify",
        "D-0001",
        "--summary",
        "Verified",
        "--verification",
        "V-0001",
    ]) == 0
    assert main([
        "--root",
        str(root),
        "defect",
        "close",
        "D-0001",
        "--summary",
        "Closed",
        "--evidence",
        "V-0001 approved",
    ]) == 0
    capsys.readouterr()


def _create_terminal_test_case(root: Path, capsys, transition: str) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "feature", "add", "--name", "Export", "--surface", "cli:pcl export"]) == 0
    if transition == "pass":
        assert main([
            "--root", str(root), "story", "draft", "--feature", "F-0001",
            "--actor", "operator", "--goal", "trace a passing test",
            "--expected-behavior", "passing evidence is reviewable",
        ]) == 0
        assert main(["--root", str(root), "story", "approve", "US-0001", "--summary", "reviewed"]) == 0
    assert main([
        "--root",
        str(root),
        "test",
        "plan",
        "--feature",
        "F-0001",
        *(["--story", "US-0001"] if transition == "pass" else []),
        "--type",
        "unit",
        "--scenario",
        f"{transition} scenario",
        "--expected",
        f"{transition} expected behavior",
    ]) == 0
    if transition == "pass":
        assert main(["--root", str(root), "goal", "create", "--title", "Validation run"]) == 0
        assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
        assert main([
            "--root",
            str(root),
            "test",
            "pass",
            "TC-0001",
            "--summary",
            "Passed",
            "--evidence",
            "pytest passed",
            "--run",
            "WR-0001",
        ]) == 0
    elif transition == "fail":
        assert main([
            "--root",
            str(root),
            "test",
            "fail",
            "TC-0001",
            "--summary",
            "Failed",
            "--evidence",
            "pytest failed",
        ]) == 0
    elif transition == "waive":
        assert main([
            "--root",
            str(root),
            "test",
            "waive",
            "TC-0001",
            "--reason",
            "Out of scope",
        ]) == 0
    else:
        raise AssertionError(f"Unsupported transition: {transition}")
    capsys.readouterr()


def test_strict_validate_rejects_closed_goal_without_proof(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Broken closure"]) == 0
    capsys.readouterr()

    _update_db(tmp_path, "UPDATE goals SET status = 'closed', completion_json = '{}' WHERE id = 'G-0001'")

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Closed goal G-0001 has no closure evidence or verification." in payload["errors"]


def test_strict_validate_rejects_passed_run_without_passed_jobs_or_verification(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    _update_db(tmp_path, "UPDATE workflow_runs SET status = 'passed' WHERE id = 'WR-0001'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Passed workflow run WR-0001 has non-passed jobs: queued=3." in payload["errors"]
    assert "Passed workflow run WR-0001 has no approved verification." in payload["errors"]


def test_validate_warns_and_strict_errors_on_invalid_rubric_v1(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
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
        "Stored before corruption",
    ]) == 0
    capsys.readouterr()

    broken_rubric = _valid_rubric()
    del broken_rubric["acceptance_criteria"]
    _update_db(
        tmp_path,
        "UPDATE verifications SET rubric_json = ? WHERE id = 'V-0001'",
        (json.dumps(broken_rubric),),
    )

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["ok"] is True
    assert "Verification V-0001 rubric/v1 invalid: acceptance_criteria is required." in normal["warnings"]

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    strict = _json_output(capsys)
    assert "Verification V-0001 rubric/v1 invalid: acceptance_criteria is required." in strict["errors"]


def test_strict_validate_rejects_missing_rubric_evidence_reference(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
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
        "Stored before corruption",
    ]) == 0
    capsys.readouterr()

    _update_db(
        tmp_path,
        "UPDATE verifications SET rubric_json = ? WHERE id = 'V-0001'",
        (json.dumps(_valid_rubric("E-9999")),),
    )

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Verification V-0001 rubric/v1 references missing evidence E-9999." in payload["errors"]


def test_strict_validate_rejects_verified_defect_without_evidence_or_verification(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
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
    capsys.readouterr()

    _update_db(tmp_path, "UPDATE defects SET status = 'verified', evidence_id = NULL WHERE id = 'D-0001'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Defect D-0001 is verified but has no evidence_id." in payload["errors"]
    assert "Defect D-0001 is verified but has no approved verification tied to the defect." in payload["errors"]


def test_strict_validate_rejects_closed_defect_missing_fix_evidence(tmp_path: Path, capsys) -> None:
    _create_closed_defect(tmp_path, capsys)

    _update_db(
        tmp_path,
        "DELETE FROM outbox_records WHERE event_id IN "
        "(SELECT id FROM events WHERE entity_id = 'D-0001' AND event_type = 'defect_fixed')",
    )
    _update_db(tmp_path, "DELETE FROM events WHERE entity_id = 'D-0001' AND event_type = 'defect_fixed'")
    _update_db(tmp_path, "DELETE FROM evidence WHERE id = 'E-0001'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Defect D-0001 is closed but has no defect_fixed event." in payload["errors"]


def test_strict_validate_rejects_closed_defect_missing_close_evidence(tmp_path: Path, capsys) -> None:
    _create_closed_defect(tmp_path, capsys)

    _update_db(tmp_path, "UPDATE defects SET evidence_id = 'E-0001' WHERE id = 'D-0001'")
    _update_db(
        tmp_path,
        "DELETE FROM outbox_records WHERE event_id IN "
        "(SELECT id FROM events WHERE entity_id = 'D-0001' AND event_type = 'defect_closed')",
    )
    _update_db(tmp_path, "DELETE FROM events WHERE entity_id = 'D-0001' AND event_type = 'defect_closed'")
    _update_db(tmp_path, "DELETE FROM evidence WHERE id = 'E-0002'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Defect D-0001 is closed but has no defect_closed event." in payload["errors"]


def test_strict_validate_accepts_terminal_test_case_evidence(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "feature", "add", "--name", "Export", "--surface", "cli:pcl export"]) == 0
    assert main([
        "--root", str(tmp_path), "story", "draft", "--feature", "F-0001",
        "--actor", "operator", "--goal", "verify terminal evidence",
        "--expected-behavior", "passing tests link reviewed behavior",
    ]) == 0
    assert main(["--root", str(tmp_path), "story", "approve", "US-0001", "--summary", "reviewed"]) == 0
    artifact = tmp_path / "pass.txt"
    artifact.write_text("pytest pass\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", "pass.txt",
        "--summary", "pass output", "--copy",
    ]) == 0
    for index, (command_name, expected_status) in enumerate(
        [("pass", "passing"), ("fail", "failing"), ("waive", "waived")],
        start=1,
    ):
        assert main([
            "--root",
            str(tmp_path),
            "test",
            "plan",
            "--feature",
            "F-0001",
            "--story",
            "US-0001",
            "--type",
            "unit",
            "--scenario",
            f"Scenario {command_name}",
            "--expected",
            f"Expected {command_name}",
        ]) == 0
        test_case_id = f"TC-{index:04d}"
        if command_name == "waive":
            assert main([
                "--root",
                str(tmp_path),
                "test",
                "waive",
                test_case_id,
                "--reason",
                "Out of scope",
            ]) == 0
        elif command_name == "pass":
            assert main([
                "--root", str(tmp_path), "test", "pass", test_case_id,
                "--summary", "pass summary", "--evidence-id", "E-0001",
            ]) == 0
        else:
            assert main([
                "--root",
                str(tmp_path),
                "test",
                command_name,
                test_case_id,
                "--summary",
                f"{command_name} summary",
                "--evidence",
                f"pytest {command_name}",
            ]) == 0
        conn = connect(tmp_path / ".project-loop" / "project.db")
        try:
            row = conn.execute(
                "SELECT status FROM test_cases WHERE id = ?",
                (test_case_id,),
            ).fetchone()
            assert row["status"] == expected_status
        finally:
            conn.close()
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}


def test_strict_validate_rejects_terminal_test_case_missing_evidence(tmp_path: Path, capsys) -> None:
    _create_terminal_test_case(tmp_path, capsys, "pass")

    _update_db(tmp_path, "DELETE FROM evidence WHERE id = 'E-0001'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Test case TC-0001 references missing evidence E-0001." in payload["errors"]
    assert (
        "Test case TC-0001 is passing but no test_case_pass evidence is linked from "
        "test_case_passed event (E-0001=missing)."
    ) in payload["errors"]


def test_strict_validate_rejects_terminal_test_case_wrong_evidence_type(tmp_path: Path, capsys) -> None:
    _create_terminal_test_case(tmp_path, capsys, "fail")

    _update_db(tmp_path, "UPDATE evidence SET type = 'defect_fix' WHERE id = 'E-0001'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert (
        "Test case TC-0001 has current evidence E-0001 with type defect_fix, "
        "expected test_case_fail."
    ) in payload["errors"]
    assert (
        "Test case TC-0001 is failing but no test_case_fail evidence is linked from "
        "test_case_failed event (E-0001=defect_fix)."
    ) in payload["errors"]


def test_strict_validate_rejects_terminal_test_case_missing_transition_event(
    tmp_path: Path,
    capsys,
) -> None:
    _create_terminal_test_case(tmp_path, capsys, "waive")

    _update_db(
        tmp_path,
        "DELETE FROM outbox_records WHERE event_id IN "
        "(SELECT id FROM events WHERE entity_id = 'TC-0001' AND event_type = 'test_case_waived')",
    )
    _update_db(tmp_path, "DELETE FROM events WHERE entity_id = 'TC-0001' AND event_type = 'test_case_waived'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Test case TC-0001 is waived but has no test_case_waived event." in payload["errors"]


def test_strict_validate_rejects_terminal_test_case_event_without_evidence_id(
    tmp_path: Path,
    capsys,
) -> None:
    _create_terminal_test_case(tmp_path, capsys, "pass")

    _update_db(
        tmp_path,
        "UPDATE events SET payload_json = ? WHERE entity_id = 'TC-0001' AND event_type = 'test_case_passed'",
        (json.dumps({"summary": "lost evidence"}),),
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Test case TC-0001 test_case_passed event has no evidence_id." in payload["errors"]


def test_strict_validate_rejects_duplicate_active_runs_for_same_target(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "regression_loop", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Duplicate active workflow runs for goal G-0001: WR-0001, WR-0002." in payload["errors"]


def test_strict_validate_rejects_duplicate_active_runs_for_same_defect(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
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
    assert main(["--root", str(tmp_path), "loop", "run", "defect_repair", "--defect", "D-0001"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "defect_repair", "--defect", "D-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Duplicate active workflow runs for defect D-0001: WR-0001, WR-0002." in payload["errors"]


def test_strict_validate_rejects_terminal_goal_with_non_terminal_task(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Cleanup"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "task",
        "create",
        "--title",
        "Still open",
        "--goal",
        "G-0001",
    ]) == 0
    capsys.readouterr()

    _update_db(
        tmp_path,
        "UPDATE goals SET status = 'closed', completion_json = ? WHERE id = 'G-0001'",
        (json.dumps({"closure": {"evidence": "Manual closure before corruption"}}),),
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Terminal goal G-0001 is closed but has non-terminal task T-0001 (todo)." in payload["errors"]


def test_strict_validate_rejects_terminal_workflow_run_with_active_job(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    _update_db(tmp_path, "UPDATE workflow_runs SET status = 'failed' WHERE id = 'WR-0001'")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Terminal workflow run WR-0001 is failed but has active agent job J-0001 (queued)." in payload["errors"]


def test_strict_validate_rejects_decision_block_link_to_missing_entity(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Which missing run should block us?",
        "--recommendation",
        "Fix the reference",
        "--blocks-json",
        json.dumps([{"type": "workflow_run", "id": "WR-9999"}]),
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Decision DEC-0001 blocks_json references missing workflow_run WR-9999." in payload["errors"]


def test_strict_validate_rejects_evidence_link_to_missing_known_target(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    _update_db(
        tmp_path,
        """
        INSERT INTO evidence(id, type, path, summary, created_at)
        VALUES ('E-0001', 'manual_note', 'inline:test', 'Inline evidence', '2026-07-08T00:00:00Z')
        """,
    )
    _update_db(
        tmp_path,
        """
        INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
        VALUES ('E-0001', 'task', 'T-9999', 'supporting', '2026-07-08T00:00:00Z')
        """,
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Evidence link E-0001 references missing task T-9999." in payload["errors"]


def test_strict_validate_tolerates_evidence_link_to_unknown_target_type(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    _update_db(
        tmp_path,
        """
        INSERT INTO evidence(id, type, path, summary, created_at)
        VALUES ('E-0001', 'manual_note', 'inline:test', 'Inline evidence', '2026-07-08T00:00:00Z')
        """,
    )
    _update_db(
        tmp_path,
        """
        INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
        VALUES ('E-0001', 'future_target', 'FT-9999', 'supporting', '2026-07-08T00:00:00Z')
        """,
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["errors"] == []


def test_strict_validate_rejects_code_context_link_target_binding_mismatch(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(tmp_path), "task", "create", "--title", "Target"]) == 0
    capsys.readouterr()
    _insert_context_receipt_link(
        tmp_path,
        evidence_id="E-0001",
        link_target_type="task",
        link_target_id="T-0001",
        link_role="code_context",
        binding_target_type="task",
        binding_target_id="T-9999",
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert any(
        "Evidence link E-0001 to task:T-0001 as code_context has an artifact "
        "target_binding that disagrees with the evidence link routing row"
        in error
        for error in payload["errors"]
    )


def test_strict_validate_accepts_matching_code_context_link_and_ignores_non_binding_roles(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    assert main(["--root", str(tmp_path), "task", "create", "--title", "Target"]) == 0
    capsys.readouterr()
    _insert_context_receipt_link(
        tmp_path,
        evidence_id="E-0001",
        link_target_type="task",
        link_target_id="T-0001",
        link_role="code_context",
        binding_target_type="task",
        binding_target_id="T-0001",
    )
    _insert_context_receipt_link(
        tmp_path,
        evidence_id="E-0002",
        link_target_type="task",
        link_target_id="T-0001",
        link_role="supporting",
        binding_target_type="task",
        binding_target_id="T-9999",
    )
    _insert_context_receipt_link(
        tmp_path,
        evidence_id="E-0003",
        link_target_type="future_target",
        link_target_id="FT-9999",
        link_role="code_context",
        binding_target_type="task",
        binding_target_id="T-9999",
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["errors"] == []


def test_strict_validate_rejects_evidence_link_to_missing_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
            VALUES ('E-9999', 'future_target', 'FT-9999', 'supporting', '2026-07-08T00:00:00Z')
            """
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert any("Evidence link E-9999 to future_target:FT-9999" in error for error in payload["errors"])


def test_strict_validate_rejects_missing_local_evidence_artifact(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    output_path = tmp_path / ".project-loop" / "evidence" / "agent-runs" / "J-0001" / "output.md"
    output_path.write_text(
        "# Mapper result\n\n"
        "## Findings\n\n"
        "- Captured one agent result.\n\n"
        "## Evidence\n\n"
        "- `.project-loop/evidence/agent-runs/J-0001/prompt.md`\n",
        encoding="utf-8",
    )
    assert main([
        "--root",
        str(tmp_path),
        "ingest-agent-run",
        ".project-loop/evidence/agent-runs/J-0001/output.md",
    ]) == 0
    capsys.readouterr()

    output_path.unlink()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Evidence E-0001 path does not exist: .project-loop/evidence/agent-runs/J-0001/output.md." in payload["errors"]
    assert "Agent job J-0001 output_path does not exist: .project-loop/evidence/agent-runs/J-0001/output.md." in payload["errors"]


def test_strict_validate_accepts_valid_closed_goal_and_defect(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    _complete_all_jobs(tmp_path, capsys, ["J-0001", "J-0002", "J-0003"])
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
        "Feature coverage passed",
    ]) == 0
    assert main(["--root", str(tmp_path), "loop", "complete", "WR-0001", "--summary", "Coverage passed"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Coverage goal complete",
        "--verification",
        "V-0001",
    ]) == 0

    assert main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
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
    assert main(["--root", str(tmp_path), "defect", "triage", "D-0001", "--summary", "Triaged"]) == 0
    assert main(["--root", str(tmp_path), "defect", "start", "D-0001", "--summary", "Started"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "fix",
        "D-0001",
        "--summary",
        "Fixed",
        "--evidence",
        "commit abc123 and regression test passed",
    ]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "defect_repair", "--defect", "D-0001"]) == 0
    _complete_all_jobs(tmp_path, capsys, ["J-0004", "J-0005", "J-0006"])
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "record",
        "--run",
        "WR-0002",
        "--result",
        "approved",
        "--reason",
        "Defect repair verified",
    ]) == 0
    assert main(["--root", str(tmp_path), "loop", "complete", "WR-0002", "--summary", "Repair passed"]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "verify",
        "D-0001",
        "--summary",
        "Verified",
        "--verification",
        "V-0002",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "defect",
        "close",
        "D-0001",
        "--summary",
        "Closed",
        "--evidence",
        "V-0002 approved",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload == {"errors": [], "ok": True, "warnings": []}
