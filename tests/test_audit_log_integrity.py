from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _events_path(root: Path) -> Path:
    return root / ".project-loop" / "events.jsonl"


def _read_events(root: Path) -> list[dict]:
    return [json.loads(line) for line in _events_path(root).read_text(encoding="utf-8").splitlines()]


def _write_events(root: Path, records: list[dict]) -> None:
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    _events_path(root).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _init_with_goal(root: Path, capsys) -> list[dict]:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    capsys.readouterr()
    return _read_events(root)


def test_strict_validate_accepts_normal_audit_log_flow(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main(["--root", str(tmp_path), "loop", "cancel", "WR-0001", "--summary", "Stop run"]) == 0
    assert main(["--root", str(tmp_path), "goal", "cancel", "G-0001", "--summary", "No longer needed"]) == 0
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
    assert main(["--root", str(tmp_path), "defect", "waive", "D-0001", "--reason", "Accepted limitation"]) == 0
    assert main(["--root", str(tmp_path), "report", "defect", "D-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json_output(capsys) == {"errors": [], "ok": True, "warnings": []}


def test_strict_validate_rejects_missing_events_jsonl(tmp_path: Path, capsys) -> None:
    _init_with_goal(tmp_path, capsys)
    _events_path(tmp_path).unlink()

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["ok"] is True
    assert any("Missing events.jsonl" in warning for warning in normal["warnings"])

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    strict = _json_output(capsys)
    assert any("Missing events.jsonl" in error for error in strict["errors"])


def test_strict_validate_rejects_invalid_jsonl(tmp_path: Path, capsys) -> None:
    _init_with_goal(tmp_path, capsys)
    _events_path(tmp_path).write_text("{not-json\n", encoding="utf-8")

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "Invalid events.jsonl line 1: Expecting property name enclosed in double quotes." in payload["errors"]


def test_strict_validate_rejects_duplicate_jsonl_event_id(tmp_path: Path, capsys) -> None:
    records = _init_with_goal(tmp_path, capsys)
    _write_events(tmp_path, [*records, records[0]])

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    expected = f"Duplicate events.jsonl event id {records[0]['id']} at lines 1 and {len(records) + 1}."
    assert expected in payload["errors"]


def test_strict_validate_rejects_db_event_missing_from_jsonl(tmp_path: Path, capsys) -> None:
    records = _init_with_goal(tmp_path, capsys)
    _write_events(tmp_path, records[1:])

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert f"DB event {records[0]['id']} is missing from events.jsonl." in payload["errors"]


def test_strict_validate_rejects_jsonl_event_missing_from_db(tmp_path: Path, capsys) -> None:
    records = _init_with_goal(tmp_path, capsys)
    extra = {
        "id": "EV-EXTRA",
        "event_type": "extra_event",
        "entity_type": "test",
        "entity_id": "test",
        "payload": {"source": "jsonl-only"},
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    _write_events(tmp_path, [*records, extra])

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert "events.jsonl event EV-EXTRA is missing from DB events table." in payload["errors"]


def test_strict_validate_rejects_payload_mismatch(tmp_path: Path, capsys) -> None:
    records = _init_with_goal(tmp_path, capsys)
    records[-1]["payload"] = {"title": "Changed"}
    _write_events(tmp_path, records)

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    assert f"Event {records[-1]['id']} payload differs between DB and events.jsonl." in payload["errors"]


def test_strict_validate_rejects_order_mismatch(tmp_path: Path, capsys) -> None:
    records = _init_with_goal(tmp_path, capsys)
    _write_events(tmp_path, list(reversed(records)))

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    payload = _json_output(capsys)
    expected = f"Event order mismatch at position 1: DB has {records[0]['id']}, events.jsonl has {records[-1]['id']}."
    assert expected in payload["errors"]
