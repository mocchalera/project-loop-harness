from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_active_run(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def _complete_jobs(root: Path, capsys) -> None:
    for job_id in ["J-0001", "J-0002", "J-0003"]:
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


def _record_needs_human(root: Path, capsys, reason: str = "Product decision required") -> None:
    assert main([
        "--root",
        str(root),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "needs_human",
        "--reason",
        reason,
    ]) == 0
    capsys.readouterr()


def _open_run_escalation(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "escalation",
        "open",
        "--run",
        "WR-0001",
        "--severity",
        "high",
        "--question",
        "Can product decide?",
    ]) == 0
    capsys.readouterr()


def test_escalation_open_read_list_resolve_and_dashboard(tmp_path: Path, capsys) -> None:
    _create_active_run(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--run",
        "WR-0001",
        "--severity",
        "high",
        "--question",
        "Can we change the login contract?",
        "--recommendation",
        "Ask product owner",
        "--json",
    ]) == 0
    opened = _json_output(capsys)
    assert opened == {
        "id": "ESC-0001",
        "ok": True,
        "question": "Can we change the login contract?",
        "recommendation": "Ask product owner",
        "severity": "high",
        "status": "open",
        "workflow_run_id": "WR-0001",
    }

    assert main(["--root", str(tmp_path), "escalation", "read", "ESC-0001", "--json"]) == 0
    read = _json_output(capsys)
    assert read["escalation"]["id"] == "ESC-0001"
    assert read["escalation"]["status"] == "open"
    assert read["escalation"]["linked_decision_ids"] == []

    assert main(["--root", str(tmp_path), "escalation", "list", "--status", "open", "--json"]) == 0
    listed = _json_output(capsys)
    assert [item["id"] for item in listed["escalations"]] == ["ESC-0001"]
    assert listed["escalations"][0]["linked_decision_ids"] == []

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "resolve_escalation"
    assert action["command"] == (
        "pcl decision open --escalation ESC-0001 "
        "--question 'Record the human decision for ESC-0001' "
        "--recommendation 'Choose the safe next step'"
    )
    assert action["target"]["linked_decision_ids"] == []

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = json.loads((tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    assert data["counts"]["open_escalations"] == 1
    assert data["escalations"][0]["id"] == "ESC-0001"

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--summary",
        "Product approved the contract change",
        "--json",
    ]) == 0
    resolved = _json_output(capsys)
    assert resolved["status"] == "resolved"

    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    _json_output(capsys)
    data = json.loads((tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    assert data["counts"]["open_escalations"] == 0

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "escalation_opened" in events
    assert "escalation_resolved" in events


def test_escalation_cancel_and_invalid_transition(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "medium",
        "--question",
        "Should this be deferred?",
        "--json",
    ]) == 0
    assert _json_output(capsys)["id"] == "ESC-0001"

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "cancel",
        "ESC-0001",
        "--summary",
        "No longer relevant",
        "--json",
    ]) == 0
    assert _json_output(capsys)["status"] == "cancelled"

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--summary",
        "Too late",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "cannot transition to resolved" in payload["error"]["message"]


def test_escalation_resolve_can_reference_linked_decision(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "high",
        "--question",
        "Needs a durable decision",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--escalation",
        "ESC-0001",
        "--question",
        "Which option should we choose?",
        "--recommendation",
        "Choose the safest option",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "resolve_escalation"
    assert action["target"]["linked_decision_ids"] == ["DEC-0001"]
    assert action["command"] == "pcl escalation resolve ESC-0001 --decision DEC-0001 --summary 'Record the outcome'"

    assert main(["--root", str(tmp_path), "escalation", "read", "ESC-0001", "--json"]) == 0
    read = _json_output(capsys)
    assert read["escalation"]["linked_decision_ids"] == ["DEC-0001"]

    assert main(["--root", str(tmp_path), "escalation", "list", "--json"]) == 0
    listed = _json_output(capsys)
    assert listed["escalations"][0]["linked_decision_ids"] == ["DEC-0001"]

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--decision",
        "DEC-0001",
        "--summary",
        "Decision recorded",
        "--json",
    ]) == 0
    resolved = _json_output(capsys)
    assert resolved["status"] == "resolved"
    assert resolved["decision_id"] == "DEC-0001"

    events = [
        json.loads(line)
        for line in (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    resolved_event = next(item for item in events if item["event_type"] == "escalation_resolved")
    assert resolved_event["payload"]["decision_id"] == "DEC-0001"


def test_escalation_resolve_rejects_missing_or_unlinked_decision(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "high",
        "--question",
        "Needs a durable decision",
    ]) == 0
    assert main([
        "--root",
        str(tmp_path),
        "decision",
        "open",
        "--question",
        "Unlinked decision",
        "--recommendation",
        "Do not accept as linked",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--decision",
        "DEC-9999",
        "--summary",
        "Missing decision",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "Decision does not exist" in payload["error"]["message"]

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--decision",
        "DEC-0001",
        "--summary",
        "Unlinked decision",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert "is not linked to escalation" in payload["error"]["message"]


def test_next_opens_escalation_for_needs_human_verification(tmp_path: Path, capsys) -> None:
    _create_active_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _record_needs_human(tmp_path, capsys)


    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "open_escalation"
    assert action["target"]["id"] == "WR-0001"
    assert action["target"]["verification_id"] == "V-0001"
    assert action["command"].startswith("pcl escalation open --run WR-0001")

    _open_run_escalation(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "resolve_escalation"


def test_resolved_escalation_suppresses_reopening_same_needs_human_verification(tmp_path: Path, capsys) -> None:
    _create_active_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _record_needs_human(tmp_path, capsys)
    _open_run_escalation(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--summary",
        "Product made the decision",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "record_verification"
    assert action["command"].startswith("pcl verification record --run WR-0001")


def test_cancelled_escalation_suppresses_reopening_same_needs_human_verification(tmp_path: Path, capsys) -> None:
    _create_active_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _record_needs_human(tmp_path, capsys)
    _open_run_escalation(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "cancel",
        "ESC-0001",
        "--summary",
        "Decision no longer blocks the run",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "record_verification"
    assert action["command"].startswith("pcl verification record --run WR-0001")


def test_newer_needs_human_verification_can_open_new_escalation_after_resolution(tmp_path: Path, capsys) -> None:
    _create_active_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _record_needs_human(tmp_path, capsys)
    _open_run_escalation(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "resolve",
        "ESC-0001",
        "--summary",
        "First decision recorded",
    ]) == 0
    capsys.readouterr()
    _record_needs_human(tmp_path, capsys, reason="A new product decision is required")

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "open_escalation"
    assert action["target"]["verification_id"] == "V-0002"
    assert action["command"].startswith("pcl escalation open --run WR-0001")


def test_next_strict_prioritizes_validation_errors_before_escalations(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "escalation",
        "open",
        "--severity",
        "high",
        "--question",
        "Needs a human",
    ]) == 0
    events_path = tmp_path / ".project-loop" / "events.jsonl"
    events_path.write_text("{bad-json\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["type"] == "resolve_escalation"

    assert main(["--root", str(tmp_path), "next", "--strict", "--json"]) == 0
    strict = _json_output(capsys)
    assert strict["type"] == "resolve_validation_errors"
