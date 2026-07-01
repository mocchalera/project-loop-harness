from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()


def _open_decision(root: Path, capsys) -> dict:
    assert main([
        "--root",
        str(root),
        "decision",
        "open",
        "--question",
        "Which rollout path should we use?",
        "--recommendation",
        "Use a guarded local release first",
        "--blocks-json",
        '[{"type":"workflow_run","id":"WR-0001"}]',
        "--json",
    ]) == 0
    return _json_output(capsys)


def _open_escalation(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "escalation",
        "open",
        "--severity",
        "high",
        "--question",
        "Which path should a human choose?",
    ]) == 0
    capsys.readouterr()


def _dashboard_data(root: Path) -> dict:
    return json.loads((root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))


def test_decision_open_read_list_resolve_and_dashboard(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    opened = _open_decision(tmp_path, capsys)
    assert opened["id"] == "DEC-0001"
    assert opened["ok"] is True
    assert opened["status"] == "open"
    assert opened["question"] == "Which rollout path should we use?"
    assert opened["recommendation"] == "Use a guarded local release first"
    assert json.loads(opened["blocks_json"]) == [{"id": "WR-0001", "type": "workflow_run"}]

    assert main(["--root", str(tmp_path), "decision", "read", "DEC-0001", "--json"]) == 0
    read = _json_output(capsys)
    assert read["decision"]["id"] == "DEC-0001"
    assert read["decision"]["status"] == "open"
    assert read["decision"]["linked_escalation_ids"] == []

    assert main(["--root", str(tmp_path), "decision", "list", "--status", "open", "--json"]) == 0
    listed = _json_output(capsys)
    assert [item["id"] for item in listed["decisions"]] == ["DEC-0001"]
    assert listed["decisions"][0]["linked_escalation_ids"] == []

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "resolve_decision"
    assert action["command"].startswith("pcl decision resolve DEC-0001")

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = _dashboard_data(tmp_path)
    assert data["counts"]["open_decisions"] == 1
    assert data["decisions"][0]["id"] == "DEC-0001"

    html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
    assert "Decision Queue" in html
    assert "DEC-0001" in html

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "resolve",
        "DEC-0001",
        "--selected-option",
        "Guarded local release",
        "--reason",
        "It keeps rollout risk local",
        "--json",
    ]) == 0
    resolved = _json_output(capsys)
    assert resolved == {
        "id": "DEC-0001",
        "ok": True,
        "reason": "It keeps rollout risk local",
        "selected_option": "Guarded local release",
        "status": "resolved",
    }

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = _dashboard_data(tmp_path)
    assert data["counts"]["open_decisions"] == 0

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "decision_opened" in events
    assert "decision_resolved" in events


def test_decision_open_can_link_to_open_escalation(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _open_escalation(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Which rollout path should we use?",
        "--recommendation",
        "Use a guarded local release first",
        "--blocks-json",
        '[{"type":"workflow_run","id":"WR-0001"},{"type":"escalation","id":"ESC-0001"}]',
        "--escalation",
        "ESC-0001",
        "--json",
    ]) == 0
    opened = _json_output(capsys)
    assert opened["id"] == "DEC-0001"
    assert opened["escalation_id"] == "ESC-0001"
    assert json.loads(opened["blocks_json"]) == [
        {"id": "WR-0001", "type": "workflow_run"},
        {"id": "ESC-0001", "type": "escalation"},
    ]

    assert main(["--root", str(tmp_path), "decision", "read", "DEC-0001", "--json"]) == 0
    read = _json_output(capsys)
    assert read["decision"]["linked_escalation_ids"] == ["ESC-0001"]

    assert main(["--root", str(tmp_path), "decision", "list", "--json"]) == 0
    listed = _json_output(capsys)
    assert listed["decisions"][0]["linked_escalation_ids"] == ["ESC-0001"]

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = _dashboard_data(tmp_path)
    assert data["decisions"][0]["linked_escalation_ids"] == ["ESC-0001"]
    assert data["escalations"][0]["linked_decision_ids"] == ["DEC-0001"]
    html = (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").read_text(encoding="utf-8")
    assert "ESC-0001" in html
    assert "DEC-0001" in html

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert '"escalation_id": "ESC-0001"' in events


def test_decision_open_rejects_missing_or_closed_escalation_link(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Missing link?",
        "--recommendation",
        "Reject it",
        "--escalation",
        "ESC-9999",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Escalation does not exist" in payload["error"]["message"]

    _open_escalation(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "cancel",
        "ESC-0001",
        "--summary",
        "Not needed",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Closed link?",
        "--recommendation",
        "Reject it",
        "--escalation",
        "ESC-0001",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot be linked to a new decision" in payload["error"]["message"]


def test_decision_waive_and_invalid_transition(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Should this decision stay open?",
        "--recommendation",
        "Waive it if it no longer blocks work",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "waive",
        "DEC-0001",
        "--reason",
        "No longer blocks work",
        "--json",
    ]) == 0
    waived = _json_output(capsys)
    assert waived["status"] == "waived"

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "resolve",
        "DEC-0001",
        "--selected-option",
        "Resolve anyway",
        "--reason",
        "Too late",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot transition to resolved" in payload["error"]["message"]


def test_decision_blocks_json_must_be_array(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "What is blocked?",
        "--recommendation",
        "Use an array",
        "--blocks-json",
        '{"id":"WR-0001"}',
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "blocks-json must be a JSON array."


def test_next_prioritizes_open_escalation_before_open_decision(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _open_decision(tmp_path, capsys)
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "high",
        "--question",
        "Needs human attention",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "resolve_escalation"

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--summary",
        "Escalation handled",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "resolve_decision"
    assert action["target"]["id"] == "DEC-0001"


def test_next_strict_prioritizes_validation_errors_before_decisions(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _open_decision(tmp_path, capsys)
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    events_path.write_text("{bad-json\n", encoding="utf-8")

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["type"] == "resolve_decision"

    assert main(["--root", str(tmp_path), "next", "--strict", "--json"]) == 0
    strict = _json_output(capsys)
    assert strict["type"] == "resolve_validation_errors"
