from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcl import verification_feedback as verification_feedback_module
from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict[str, Any]:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _insert_evidence(
    root: Path,
    *,
    evidence_id: str,
    evidence_type: str,
    path: str,
    summary: str = "Test evidence.",
) -> None:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, evidence_type, path, "test setup", summary, "2026-07-06T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _create_receipt(
    root: Path,
    *,
    evidence_id: str = "E-0001",
    suggestions: list[Any] | None = None,
) -> str:
    receipt_dir = root / ".project-loop" / "evidence" / "context-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{evidence_id.lower()}-impact-v0.json"
    relative_path = f".project-loop/evidence/context-receipts/{receipt_path.name}"
    payload = {
        "contract_version": "context-receipt/v0",
        "created_at": "2026-07-06T00:00:00Z",
        "evidence_id": evidence_id,
        "receipt_path": relative_path,
        "verification_suggestions": suggestions
        if suggestions is not None
        else [
            {
                "id": f"{evidence_id}/VS-01",
                "command": "python3 -m pytest tests/test_cli.py",
                "reason": "test_hint:path_token_match",
            }
        ],
    }
    receipt_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    _insert_evidence(
        root,
        evidence_id=evidence_id,
        evidence_type="context_receipt",
        path=relative_path,
        summary="Context receipt.",
    )
    return relative_path


def _create_supporting_evidence(root: Path, evidence_id: str = "E-0009") -> None:
    _insert_evidence(
        root,
        evidence_id=evidence_id,
        evidence_type="command_result",
        path=f"inline:{evidence_id}",
        summary="Caller supplied command result.",
    )


def _create_adhoc_supporting_evidence(
    root: Path,
    capsys,
    *,
    filename: str = "pytest-out.txt",
    content: str = "pytest passed\n",
) -> dict[str, Any]:
    artifact = root / filename
    artifact.write_text(content, encoding="utf-8")
    assert main([
        "--root",
        str(root),
        "evidence",
        "add",
        "--file",
        filename,
        "--summary",
        "Caller supplied pytest output.",
        "--json",
    ]) == 0
    return _json_output(capsys)["evidence"]


def _feedback_rows(root: Path) -> list[dict[str, Any]]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        rows = conn.execute(
            """
            SELECT id, suggestion_id, status, result, supporting_evidence_id, note
            FROM verification_feedback
            ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _event_count(root: Path) -> int:
    return len((root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines())


def _event_file_size(root: Path) -> int:
    return (root / ".project-loop" / "events.jsonl").stat().st_size


def _table_count(root: Path, table_name: str) -> int:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    finally:
        conn.close()


def _assert_feedback_error(capsys, code: str) -> None:
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["error"]["code"] == code


def test_verification_feedback_cli_rejects_status_result_evidence_boundaries(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    before_events = _event_count(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--json",
    ]) == 2
    _assert_feedback_error(capsys, "verification_feedback_result_required")
    assert _feedback_rows(tmp_path) == []
    assert _event_count(tmp_path) == before_events

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--json",
    ]) == 2
    _assert_feedback_error(capsys, "verification_feedback_evidence_required")
    assert _feedback_rows(tmp_path) == []
    assert _event_count(tmp_path) == before_events

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "skipped",
        "--result",
        "passed",
        "--json",
    ]) == 2
    _assert_feedback_error(capsys, "verification_feedback_result_not_allowed")
    assert _feedback_rows(tmp_path) == []
    assert _event_count(tmp_path) == before_events


def test_verification_feedback_referential_errors_do_not_mutate_state(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_supporting_evidence(tmp_path)
    before_events = _event_count(tmp_path)

    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-9999/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        "E-0009",
        "--json",
    ]) == 2
    _assert_feedback_error(capsys, "verification_feedback_unknown_receipt")
    assert _feedback_rows(tmp_path) == []
    assert _event_count(tmp_path) == before_events

    _insert_evidence(
        tmp_path,
        evidence_id="E-0001",
        evidence_type="context_receipt",
        path=".project-loop/evidence/context-receipts/missing.json",
        summary="Missing receipt artifact.",
    )
    before_events = _event_count(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        "E-0009",
        "--json",
    ]) == 2
    _assert_feedback_error(capsys, "verification_feedback_unreadable_receipt")
    assert _feedback_rows(tmp_path) == []
    assert _event_count(tmp_path) == before_events

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("DELETE FROM evidence WHERE id = ?", ("E-0001",))
        conn.commit()
    finally:
        conn.close()
    _create_receipt(tmp_path, evidence_id="E-0001")
    before_events = _event_count(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-99",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        "E-0009",
        "--json",
    ]) == 2
    _assert_feedback_error(capsys, "verification_feedback_suggestion_absent")
    assert _feedback_rows(tmp_path) == []
    assert _event_count(tmp_path) == before_events


def test_verification_feedback_accepts_multiple_rows_and_appends_events(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(tmp_path)
    _create_supporting_evidence(tmp_path)
    before_events = _event_count(tmp_path)

    for result in ["passed", "failed"]:
        assert main([
            "--root",
            str(tmp_path),
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-01",
            "--status",
            "executed",
            "--result",
            result,
            "--evidence",
            "E-0009",
            "--note",
            f"Caller reported {result}",
            "--json",
        ]) == 0
        _json_output(capsys)

    rows = _feedback_rows(tmp_path)
    assert [row["id"] for row in rows] == ["VF-0001", "VF-0002"]
    assert [row["result"] for row in rows] == ["passed", "failed"]
    assert _event_count(tmp_path) == before_events + 2

    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    latest = _json_output(capsys)["stats"]["latest_feedback_by_suggestion"]
    assert latest["E-0001/VS-01"]["id"] == "VF-0002"
    assert latest["E-0001/VS-01"]["result"] == "failed"


def test_verification_stats_counts_addressable_feedback_events_and_warnings(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(
        tmp_path,
        evidence_id="E-0001",
        suggestions=[
            {
                "id": "E-0001/VS-01",
                "command": "python3 -m pytest tests/test_cli.py",
                "reason": "test_hint:path_token_match",
            },
            {
                "id": "E-0001/VS-02",
                "command": "python3 -m pytest tests/test_migrations.py",
                "reason": "test_hint:path_token_match",
            },
            "python3 -m pytest legacy_tests.py",
        ],
    )
    _create_receipt(
        tmp_path,
        evidence_id="E-0002",
        suggestions=["python3 -m pytest old_receipt.py"],
    )
    _insert_evidence(
        tmp_path,
        evidence_id="E-0003",
        evidence_type="context_receipt",
        path=".project-loop/evidence/context-receipts/unreadable.json",
        summary="Unreadable receipt artifact.",
    )
    _create_supporting_evidence(tmp_path, "E-0009")

    commands = [
        [
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-01",
            "--status",
            "executed",
            "--result",
            "passed",
            "--evidence",
            "E-0009",
        ],
        [
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-01",
            "--status",
            "executed",
            "--result",
            "failed",
            "--evidence",
            "E-0009",
        ],
        [
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-02",
            "--status",
            "skipped",
            "--note",
            "Caller skipped this suggestion.",
        ],
    ]
    for command in commands:
        assert main(["--root", str(tmp_path), *command, "--json"]) == 0
        _json_output(capsys)

    before_events = _event_count(tmp_path)
    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    payload = _json_output(capsys)

    stats = payload["stats"]
    assert stats["receipts_scanned"] == 3
    assert stats["receipts_unreadable_count"] == 1
    assert len(stats["warnings"]) == 1
    assert "E-0003" in stats["warnings"][0]
    assert stats["addressable_issued_suggestions_count"] == 2
    assert stats["unaddressable_legacy_suggestions_count"] == 2
    assert stats["feedback_coverage_numerator"] == 2
    assert stats["feedback_coverage_denominator"] == 2
    assert stats["feedback_coverage_rate"] == 1.0
    assert stats["execution_numerator"] == 1
    assert stats["execution_denominator"] == 2
    assert stats["execution_rate"] == 0.5
    assert stats["executed_feedback_events_count"] == 2
    assert stats["executed_pass_numerator"] == 1
    assert stats["executed_pass_denominator"] == 2
    assert stats["executed_pass_rate"] == 0.5
    assert stats["executed_fail_numerator"] == 1
    assert stats["executed_fail_denominator"] == 2
    assert stats["executed_fail_rate"] == 0.5
    assert _event_count(tmp_path) == before_events


def test_verification_stats_uses_null_rates_for_empty_denominators(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(
        tmp_path,
        evidence_id="E-0001",
        suggestions=["python3 -m pytest legacy_only.py"],
    )

    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    stats = _json_output(capsys)["stats"]

    assert stats["addressable_issued_suggestions_count"] == 0
    assert stats["unaddressable_legacy_suggestions_count"] == 1
    assert stats["feedback_coverage_denominator"] == 0
    assert stats["feedback_coverage_rate"] is None
    assert stats["execution_denominator"] == 0
    assert stats["execution_rate"] is None
    assert stats["executed_pass_denominator"] == 0
    assert stats["executed_pass_rate"] is None
    assert stats["executed_fail_denominator"] == 0
    assert stats["executed_fail_rate"] is None


def test_verification_stats_reports_adhoc_supporting_evidence_health_and_does_not_write(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(
        tmp_path,
        evidence_id="E-0001",
        suggestions=[
            {
                "id": "E-0001/VS-01",
                "command": "python3 -m pytest tests/test_cli.py",
                "reason": "test_hint:path_token_match",
            },
            {
                "id": "E-0001/VS-02",
                "command": "python3 -m pytest tests/test_migrations.py",
                "reason": "test_hint:path_token_match",
            },
            {
                "id": "E-0001/VS-03",
                "command": "python3 -m pytest tests/test_reports.py",
                "reason": "test_hint:path_token_match",
            },
        ],
    )
    evidence = _create_adhoc_supporting_evidence(tmp_path, capsys)
    manifest_path = tmp_path / evidence["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["members"][0]["path_scope"] = "workspace"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    commands = [
        [
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-01",
            "--status",
            "executed",
            "--result",
            "passed",
            "--evidence",
            evidence["id"],
        ],
        [
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-02",
            "--status",
            "skipped",
            "--evidence",
            evidence["id"],
        ],
        [
            "verification",
            "feedback",
            "--suggestion",
            "E-0001/VS-03",
            "--status",
            "skipped",
        ],
    ]
    for command in commands:
        assert main(["--root", str(tmp_path), *command, "--json"]) == 0
        _json_output(capsys)

    original_assess = verification_feedback_module.assess_adhoc_evidence
    assessment_calls: list[str] = []

    def counting_assess(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assessment_calls.append(str(kwargs["evidence_id"]))
        return original_assess(*args, **kwargs)

    monkeypatch.setattr(verification_feedback_module, "assess_adhoc_evidence", counting_assess)
    before_event_size = _event_file_size(tmp_path)
    before_evidence_count = _table_count(tmp_path, "evidence")
    before_feedback_count = _table_count(tmp_path, "verification_feedback")

    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    stats = _json_output(capsys)["stats"]

    assert assessment_calls == [evidence["id"]]
    assert stats["executed_pass_rate"] == 1.0
    health = stats["supporting_evidence_health"]
    assert health == {
        "assessed_evidence_count": 1,
        "feedback_events_with_supporting_evidence_count": 2,
        "health_counts": {"ok": 1, "warning": 0, "error": 0, "unknown": 0},
        "by_evidence_id": {evidence["id"]: {"health": "ok", "findings": []}},
    }
    latest = stats["latest_feedback_by_suggestion"]
    assert latest["E-0001/VS-01"]["supporting_evidence_health"] == "ok"
    assert latest["E-0001/VS-02"]["supporting_evidence_health"] == "ok"
    assert latest["E-0001/VS-03"]["supporting_evidence_health"] is None
    assert _event_file_size(tmp_path) == before_event_size
    assert _table_count(tmp_path, "evidence") == before_evidence_count
    assert _table_count(tmp_path, "verification_feedback") == before_feedback_count


def test_verification_stats_reports_adhoc_member_drift_without_changing_metrics(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(tmp_path)
    evidence = _create_adhoc_supporting_evidence(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        evidence["id"],
        "--json",
    ]) == 0
    _json_output(capsys)

    (tmp_path / "pytest-out.txt").write_text("pytest failed\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    changed_stats = _json_output(capsys)["stats"]
    changed_health = changed_stats["supporting_evidence_health"]["by_evidence_id"][evidence["id"]]
    assert changed_stats["executed_pass_rate"] == 1.0
    assert changed_health == {
        "health": "warning",
        "findings": [{"code": "member_hash_mismatch", "path": "pytest-out.txt"}],
    }

    (tmp_path / "pytest-out.txt").unlink()
    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    missing_stats = _json_output(capsys)["stats"]
    missing_health = missing_stats["supporting_evidence_health"]["by_evidence_id"][evidence["id"]]
    assert missing_stats["executed_pass_rate"] == 1.0
    assert missing_health == {
        "health": "warning",
        "findings": [{"code": "member_missing", "path": "pytest-out.txt"}],
    }


def test_verification_stats_reports_missing_adhoc_manifest_error(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(tmp_path)
    evidence = _create_adhoc_supporting_evidence(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        evidence["id"],
        "--json",
    ]) == 0
    _json_output(capsys)

    (tmp_path / evidence["manifest_path"]).unlink()
    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    health = _json_output(capsys)["stats"]["supporting_evidence_health"]
    assert health["health_counts"] == {"ok": 0, "warning": 0, "error": 1, "unknown": 0}
    assert health["by_evidence_id"][evidence["id"]] == {
        "health": "error",
        "findings": [
            {
                "code": "manifest_missing",
                "path": evidence["manifest_path"],
            }
        ],
    }


def test_verification_stats_reports_unknown_type_and_missing_evidence_row(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(
        tmp_path,
        evidence_id="E-0001",
        suggestions=[
            {
                "id": "E-0001/VS-01",
                "command": "python3 -m pytest tests/test_cli.py",
                "reason": "test_hint:path_token_match",
            },
            {
                "id": "E-0001/VS-02",
                "command": "python3 -m pytest tests/test_migrations.py",
                "reason": "test_hint:path_token_match",
            },
        ],
    )
    _create_supporting_evidence(tmp_path, "E-0009")
    _create_supporting_evidence(tmp_path, "E-0010")
    for suggestion_id, evidence_id in [
        ("E-0001/VS-01", "E-0009"),
        ("E-0001/VS-02", "E-0010"),
    ]:
        assert main([
            "--root",
            str(tmp_path),
            "verification",
            "feedback",
            "--suggestion",
            suggestion_id,
            "--status",
            "executed",
            "--result",
            "passed",
            "--evidence",
            evidence_id,
            "--json",
        ]) == 0
        _json_output(capsys)

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM evidence WHERE id = ?", ("E-0010",))
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "verification", "stats", "--json"]) == 0
    health = _json_output(capsys)["stats"]["supporting_evidence_health"]
    assert health["health_counts"] == {"ok": 0, "warning": 0, "error": 1, "unknown": 1}
    assert health["by_evidence_id"]["E-0009"] == {
        "health": "unknown",
        "findings": [{"code": "health_not_assessed_for_type", "detail": "command_result"}],
    }
    assert health["by_evidence_id"]["E-0010"] == {
        "health": "error",
        "findings": [{"code": "evidence_row_missing"}],
    }


def test_strict_validate_reports_verification_feedback_missing_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    _create_receipt(tmp_path)
    _create_supporting_evidence(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "verification",
        "feedback",
        "--suggestion",
        "E-0001/VS-01",
        "--status",
        "executed",
        "--result",
        "passed",
        "--evidence",
        "E-0009",
        "--json",
    ]) == 0
    _json_output(capsys)

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "UPDATE verification_feedback SET supporting_evidence_id = ? WHERE id = ?",
            ("E-9999", "VF-0001"),
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert (
        "Verification feedback VF-0001 references missing supporting evidence E-9999."
        in payload["errors"]
    )
