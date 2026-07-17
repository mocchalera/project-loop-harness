from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

import pcl.cli as cli_module
from pcl.audit import rebuild_jsonl_from_sqlite
from pcl.cli import main
from pcl.db import connect
from pcl.paths import resolve_paths


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _events(root: Path) -> list[dict]:
    path = root / ".project-loop" / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_events(root: Path, events: list[object]) -> None:
    path = root / ".project-loop" / "events.jsonl"
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _insert_pending_event(root: Path, event_id: str = "EV-PENDING") -> int:
    db_path = root / ".project-loop" / "project.db"
    conn = connect(db_path)
    try:
        sequence = int(
            conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM events").fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO events(id, sequence, event_type, entity_type, entity_id, payload_json, created_at)
            VALUES (?, ?, 'fixture_pending', 'test', NULL, '{}', '2026-07-10T00:00:00Z')
            """,
            (event_id, sequence),
        )
        conn.execute(
            """
            INSERT INTO outbox_records(
              id, event_id, sink, idempotency_key, status, attempts,
              created_at, updated_at
            ) VALUES (?, ?, 'jsonl', ?, 'pending', 0,
                      '2026-07-10T00:00:00Z', '2026-07-10T00:00:00Z')
            """,
            (f"OB-{event_id}", event_id, f"jsonl:{event_id}"),
        )
        conn.commit()
        return sequence
    finally:
        conn.close()


def _anomaly_types(report: dict, classification: str) -> set[str]:
    return {item["type"] for item in report["anomalies"][classification]}


def test_audit_check_clean_is_read_only_and_stdout_pure(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    db_path = tmp_path / ".project-loop" / "project.db"
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    before_hashes = (_sha256(db_path), _sha256(events_path))
    before_files = sorted(
        str(path.relative_to(tmp_path))
        for path in (tmp_path / ".project-loop").rglob("*")
        if path.is_file()
    )

    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 0
    report = _json_output(capsys)

    assert report["contract_version"] == "audit-check/v1"
    assert report["ok"] is True
    assert report["status"] == "clean"
    assert report["counts"]["db_events"] == report["counts"]["jsonl_events"]
    assert report["counts"]["anomalies"] == 0
    assert report["hashes"] == {
        "jsonl_sha256": before_hashes[1],
        "sqlite_sha256": before_hashes[0],
    }
    assert (_sha256(db_path), _sha256(events_path)) == before_hashes
    assert sorted(
        str(path.relative_to(tmp_path))
        for path in (tmp_path / ".project-loop").rglob("*")
        if path.is_file()
    ) == before_files


@pytest.mark.parametrize(
    ("corruption", "classification", "anomaly_type", "exit_code"),
    [
        ("missing", "human_review", "missing_jsonl_event", 6),
        ("duplicate", "human_review", "duplicate_jsonl_event", 6),
        ("gap", "unsupported", "db_sequence_gap", 7),
        ("orphan_outbox", "unsupported", "orphan_outbox", 7),
        ("mismatch", "human_review", "jsonl_event_mismatch", 6),
    ],
)
def test_audit_check_corruption_fixture_matrix(
    tmp_path: Path,
    capsys,
    corruption: str,
    classification: str,
    anomaly_type: str,
    exit_code: int,
) -> None:
    _init(tmp_path, capsys)
    events = _events(tmp_path)
    db_path = tmp_path / ".project-loop" / "project.db"
    if corruption == "missing":
        _write_events(tmp_path, events[:-1])
    elif corruption == "duplicate":
        _write_events(tmp_path, [*events, events[0]])
    elif corruption == "gap":
        conn = connect(db_path)
        try:
            conn.execute(
                "UPDATE events SET sequence = sequence + 1 WHERE sequence = (SELECT MAX(sequence) FROM events)"
            )
            conn.commit()
        finally:
            conn.close()
    elif corruption == "orphan_outbox":
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                INSERT INTO outbox_records(
                  id, event_id, sink, idempotency_key, status, attempts,
                  created_at, updated_at
                ) VALUES ('OB-ORPHAN', 'EV-NOT-FOUND', 'jsonl', 'jsonl:EV-NOT-FOUND',
                          'pending', 0, 'now', 'now')
                """
            )
            conn.commit()
        finally:
            conn.close()
    elif corruption == "mismatch":
        events[-1]["payload"] = {"fixture": "changed"}
        _write_events(tmp_path, events)

    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == exit_code
    report = _json_output(capsys)
    assert anomaly_type in _anomaly_types(report, classification)


def test_pending_outbox_repair_preview_then_apply_is_once_only_and_audited(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    event_id = "EV-PENDING-REPAIR"
    _insert_pending_event(tmp_path, event_id)
    db_path = tmp_path / ".project-loop" / "project.db"
    events_path = tmp_path / ".project-loop" / "events.jsonl"

    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 6
    check = _json_output(capsys)
    assert "outbox_pending" in _anomaly_types(check, "repairable")
    assert "missing_jsonl_event" in _anomaly_types(check, "repairable")

    before_hashes = (_sha256(db_path), _sha256(events_path))
    assert main(["--root", str(tmp_path), "audit", "repair", "--dry-run", "--json"]) == 0
    preview = _json_output(capsys)
    assert preview["dry_run"] is True
    assert preview["applied"] is False
    assert preview["plan"]["actions"] == ["flush_outbox"]
    assert (_sha256(db_path), _sha256(events_path)) == before_hashes

    assert main(["--root", str(tmp_path), "audit", "repair", "--apply", "--json"]) == 0
    applied = _json_output(capsys)
    assert applied["applied"] is True
    assert applied["backup"]["sha256"] == before_hashes[1]
    backup = tmp_path / applied["backup"]["path"]
    assert backup.is_file()
    assert _sha256(backup) == before_hashes[1]
    assert applied["artifact_hashes"]["after_jsonl_sha256"] == _sha256(events_path)

    projected = _events(tmp_path)
    assert sum(event["id"] == event_id for event in projected) == 1
    assert sum(event["event_type"] == "audit_repair_applied" for event in projected) == 1
    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 0
    assert _json_output(capsys)["ok"] is True


def test_repair_refuses_review_required_corruption(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    events = _events(tmp_path)
    _write_events(tmp_path, [*events, events[0]])
    before = (tmp_path / ".project-loop" / "events.jsonl").read_bytes()

    assert main(["--root", str(tmp_path), "audit", "repair", "--dry-run", "--json"]) == 6
    preview = _json_output(capsys)
    assert "duplicate_jsonl_event" in preview["plan"]["blocking_anomaly_types"]
    assert main(["--root", str(tmp_path), "audit", "repair", "--apply", "--json"]) == 6
    applied = _json_output(capsys)
    assert applied["refused"] is True
    assert (tmp_path / ".project-loop" / "events.jsonl").read_bytes() == before


def test_repair_unsupported_format_uses_exit_7_without_mutation(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    events_path.write_bytes(events_path.read_bytes() + b'{"legacy":true}\n')
    before = events_path.read_bytes()

    assert main(["--root", str(tmp_path), "audit", "repair", "--dry-run", "--json"]) == 7
    preview = _json_output(capsys)
    assert "unknown_or_legacy_jsonl_line" in preview["plan"]["blocking_anomaly_types"]
    assert main(["--root", str(tmp_path), "audit", "repair", "--apply", "--json"]) == 7
    applied = _json_output(capsys)
    assert applied["refused"] is True
    assert events_path.read_bytes() == before


def test_rebuild_preserves_unknown_lines_in_backup_and_matches_sqlite(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    original = events_path.read_bytes() + b'{"legacy":true}\n'
    events_path.write_bytes(original)
    preview_path = tmp_path / "rebuilt-preview.jsonl"

    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 7
    assert "unknown_or_legacy_jsonl_line" in _anomaly_types(
        _json_output(capsys), "unsupported"
    )
    assert main(
        [
            "--root",
            str(tmp_path),
            "audit",
            "rebuild-jsonl",
            "--from-sqlite",
            "--output",
            str(preview_path),
            "--json",
        ]
    ) == 0
    preview = _json_output(capsys)
    assert preview["applied"] is False
    assert preview_path.is_file()
    assert events_path.read_bytes() == original

    assert main(
        [
            "--root",
            str(tmp_path),
            "audit",
            "rebuild-jsonl",
            "--from-sqlite",
            "--apply",
            "--json",
        ]
    ) == 0
    applied = _json_output(capsys)
    backup = tmp_path / applied["backup"]["path"]
    assert backup.read_bytes() == original
    assert applied["isolated_lines"] == [
        {
            "event_id": None,
            "line": len(_events(tmp_path)),
            "preserved_in": applied["backup"]["path"],
            "type": "unknown_or_legacy_jsonl_line",
        }
    ]
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        db_ids = [row["id"] for row in conn.execute("SELECT id FROM events ORDER BY sequence")]
    finally:
        conn.close()
    assert [event["id"] for event in _events(tmp_path)] == db_ids
    assert _events(tmp_path)[-1]["event_type"] == "audit_jsonl_rebuilt"


def test_atomic_rebuild_interruption_leaves_old_jsonl_intact(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    paths = resolve_paths(tmp_path)
    before = paths.events_path.read_bytes()

    def interrupt(point: str) -> None:
        assert point == "after_temp_validation_before_replace"
        raise RuntimeError("injected interruption")

    with pytest.raises(RuntimeError, match="injected interruption"):
        rebuild_jsonl_from_sqlite(paths, output=None, apply=True, fault=interrupt)

    assert paths.events_path.read_bytes() == before
    assert len(list(paths.events_path.parent.glob(".events.jsonl.rebuild.*.tmp"))) == 1


def test_rebuild_preview_refuses_to_overwrite_existing_output(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    output = tmp_path / "existing.jsonl"
    output.write_text("preserve me\n", encoding="utf-8")

    assert main(
        [
            "--root",
            str(tmp_path),
            "audit",
            "rebuild-jsonl",
            "--from-sqlite",
            "--output",
            str(output),
            "--json",
        ]
    ) == 6
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "audit_rebuild_output_exists"
    assert output.read_text(encoding="utf-8") == "preserve me\n"


def test_rebuild_exit_code_matrix_for_unsupported_db_and_io_failure(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsupported_root = tmp_path / "unsupported"
    _init(unsupported_root, capsys)
    conn = connect(unsupported_root / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE events SET sequence = sequence + 1 WHERE sequence = (SELECT MAX(sequence) FROM events)"
        )
        conn.commit()
    finally:
        conn.close()
    assert main(
        [
            "--root",
            str(unsupported_root),
            "audit",
            "rebuild-jsonl",
            "--from-sqlite",
            "--json",
        ]
    ) == 7
    assert _json_output(capsys)["error"]["code"] == "audit_unsupported_sqlite"

    io_root = tmp_path / "io"
    _init(io_root, capsys)

    def fail_rebuild(*args, **kwargs):
        raise OSError("injected rebuild I/O failure")

    monkeypatch.setattr(cli_module, "rebuild_jsonl_from_sqlite", fail_rebuild)
    assert main(
        [
            "--root",
            str(io_root),
            "audit",
            "rebuild-jsonl",
            "--from-sqlite",
            "--json",
        ]
    ) == 6
    assert _json_output(capsys)["error"]["code"] == "audit_rebuild_io_error"


def test_audit_check_reports_evidence_missing_hash_mismatch_and_orphan_temp(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    source = tmp_path / "artifact.txt"
    source.write_text("original", encoding="utf-8")
    assert main(
        [
            "--root",
            str(tmp_path),
            "evidence",
            "add",
            "--file",
            str(source),
            "--summary",
            "fixture",
            "--json",
        ]
    ) == 0
    evidence = _json_output(capsys)["evidence"]
    source.write_text("changed", encoding="utf-8")
    orphan = tmp_path / ".project-loop" / "evidence" / "orphan.tmp"
    orphan.write_text("partial", encoding="utf-8")
    orphan_packet = tmp_path / ".project-loop" / "evidence" / "completion-packets" / "orphan.json"
    orphan_packet.parent.mkdir(parents=True, exist_ok=True)
    orphan_packet.write_text("{}\n", encoding="utf-8")
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at)
            VALUES ('E-MISSING', 'fixture', 'missing-evidence.txt', 'missing', 'now')
            """
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 6
    report = _json_output(capsys)
    types = _anomaly_types(report, "human_review")
    assert {
        "evidence_file_missing",
        "evidence_metadata_file_mismatch",
        "orphan_temp_evidence",
        "orphan_completion_packet",
    }.issubset(types)
    assert report["counts"]["evidence_missing_files"] == 1
    assert report["counts"]["orphan_temp_evidence"] == 1
    assert report["counts"]["orphan_completion_packets"] == 1
    assert evidence["id"] in {
        item["details"].get("evidence_id")
        for item in report["anomalies"]["human_review"]
    }


def test_audit_check_classifies_evidence_mismatch_impact_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)

    def add_copy(name: str, content: str) -> dict:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        assert main([
            "--root", str(tmp_path), "evidence", "add", "--file", name,
            "--summary", name, "--copy", "--json",
        ]) == 0
        return _json_output(capsys)["evidence"]

    historical = add_copy("historical.txt", "historical\n")
    replacement = add_copy("replacement.txt", "replacement\n")
    (tmp_path / "historical.txt").write_text("rewritten historical\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "supersede", historical["id"],
        "--with", replacement["id"], "--summary", "new proof", "--json",
    ]) == 0
    _json_output(capsys)

    source_drift = add_copy("source-drift.txt", "source\n")
    (tmp_path / "source-drift.txt").write_text("rewritten source\n", encoding="utf-8")

    copy_corruption = add_copy("copy-corruption.txt", "copy\n")
    stored_copy = tmp_path / copy_corruption["members"][0]["stored_path"]
    stored_copy.write_text("damaged copy\n", encoding="utf-8")

    db_path = tmp_path / ".project-loop" / "project.db"
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    before_hashes = (_sha256(db_path), _sha256(events_path))

    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 6
    report = _json_output(capsys)

    assert (_sha256(db_path), _sha256(events_path)) == before_hashes
    mismatches = {
        item["details"]["evidence_id"]: item["details"]
        for item in report["anomalies"]["human_review"]
        if item["type"] == "evidence_metadata_file_mismatch"
    }
    assert mismatches[historical["id"]]["evidence_impact"] == (
        "superseded_historical_drift"
    )
    assert mismatches[historical["id"]]["superseded_by"] == replacement["id"]
    assert mismatches[historical["id"]]["durable_copy_healthy"] is True
    assert mismatches[source_drift["id"]]["evidence_impact"] == (
        "current_source_drift_with_healthy_copy"
    )
    assert mismatches[source_drift["id"]]["superseded_by"] is None
    assert mismatches[source_drift["id"]]["durable_copy_healthy"] is True
    assert mismatches[copy_corruption["id"]]["evidence_impact"] == (
        "current_durable_copy_corruption"
    )
    assert mismatches[copy_corruption["id"]]["durable_copy_healthy"] is False
    assert report["counts"]["evidence_mismatches_by_impact"] == {
        "current_durable_copy_corruption": 1,
        "current_evidence_corruption": 0,
        "current_source_drift_with_healthy_copy": 1,
        "superseded_historical_drift": 1,
    }


def test_audit_internal_failure_uses_exit_8_and_json_stdout(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init(tmp_path, capsys)

    def fail_check(paths):
        raise OSError("injected read failure")

    monkeypatch.setattr(cli_module, "audit_check", fail_check)
    assert main(["--root", str(tmp_path), "audit", "check", "--json"]) == 8
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "audit_internal_error"
