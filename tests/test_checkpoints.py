from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()


def _add_done_feature(root: Path, capsys, index: int) -> str:
    assert main([
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        f"Feature {index}",
        "--surface",
        f"surface:{index}",
        "--json",
    ]) == 0
    feature_id = str(_json_output(capsys)["id"])
    assert main([
        "--root", str(root), "story", "draft", "--feature", feature_id,
        "--actor", "operator", "--goal", f"complete feature {index}",
        "--expected-behavior", f"Feature {index} is verified",
    ]) == 0
    capsys.readouterr()
    story_id = f"US-{index:04d}"
    assert main(["--root", str(root), "story", "approve", story_id, "--summary", "reviewed"]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(root), "test", "plan", "--feature", feature_id, "--story", story_id,
        "--type", "acceptance", "--scenario", f"Feature {index} works", "--expected", "passing",
    ]) == 0
    capsys.readouterr()
    artifact = root / f"feature-{index}-result.txt"
    artifact.write_text("passed\n", encoding="utf-8")
    assert main([
        "--root", str(root), "evidence", "add", "--file", artifact.name,
        "--summary", f"Feature {index} acceptance", "--copy", "--json",
    ]) == 0
    evidence_id = str(_json_output(capsys)["evidence"]["id"])
    test_id = f"TC-{index:04d}"
    assert main([
        "--root", str(root), "test", "pass", test_id, "--summary", "passed",
        "--evidence-id", evidence_id,
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(root),
        "feature",
        "status",
        feature_id,
        "--status",
        "done",
        "--summary",
        f"Feature {index} complete",
        "--evidence-id",
        evidence_id,
        "--json",
    ]) == 0
    _json_output(capsys)
    return feature_id


def test_checkpoint_status_and_record_are_event_backed(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_ids = [_add_done_feature(tmp_path, capsys, index) for index in range(1, 6)]

    assert main(["--root", str(tmp_path), "checkpoint", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["checkpoint_recommended"] is True
    assert status["threshold"] == 5
    assert status["completed_features_since_checkpoint"] == 5
    assert status["completed_feature_ids_since_checkpoint"] == feature_ids
    assert status["feature_status_counts"]["done"] == 5
    assert status["latest_checkpoint"] is None

    assert main([
        "--root",
        str(tmp_path),
        "checkpoint",
        "record",
        "--summary",
        "Reviewed commit boundary and UX checklist",
        "--evidence",
        "Reviewed git diff, validation output, and UX checklist",
        "--review-type",
        "ux",
        "--json",
    ]) == 0
    recorded = _json_output(capsys)
    assert recorded["ok"] is True
    assert recorded["checkpoint_id"] == "E-0006"
    assert recorded["evidence_id"] == "E-0006"
    assert recorded["review_type"] == "ux"
    assert recorded["status_before"]["completed_features_since_checkpoint"] == 5
    assert recorded["status_after"] == {
        "checkpoint_recommended": False,
        "completed_features_since_checkpoint": 0,
    }

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        evidence = conn.execute("SELECT type, path, command, summary FROM evidence WHERE id = ?", ("E-0006",)).fetchone()
        event = conn.execute(
            """
            SELECT event_type, entity_type, entity_id, payload_json
            FROM events
            WHERE event_type = 'checkpoint_recorded'
            """
        ).fetchone()
    finally:
        conn.close()
    assert dict(evidence) == {
        "command": "pcl checkpoint record",
        "path": "inline:checkpoint/ux",
        "summary": "Reviewed git diff, validation output, and UX checklist",
        "type": "checkpoint_review",
    }
    assert event["event_type"] == "checkpoint_recorded"
    assert event["entity_type"] == "checkpoint"
    assert event["entity_id"] == "E-0006"
    payload = json.loads(event["payload_json"])
    assert payload["summary"] == "Reviewed commit boundary and UX checklist"
    assert payload["evidence_id"] == "E-0006"
    assert payload["review_type"] == "ux"


def test_checkpoint_record_requires_evidence_as_typed_json(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main([
        "--root",
        str(tmp_path),
        "checkpoint",
        "record",
        "--summary",
        "No evidence",
        "--evidence",
        "",
        "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"] == {"field": "evidence"}

    assert main([
        "--root",
        str(tmp_path),
        "checkpoint",
        "record",
        "--summary",
        "Bad type",
        "--evidence",
        "Evidence exists",
        "--review-type",
        "unknown",
        "--json",
    ]) == 2
    invalid_type = _json_output(capsys)
    assert invalid_type["error"]["code"] == "invalid_input"
    assert invalid_type["error"]["details"] == {
        "allowed": ["commit", "integration", "package", "release", "ux"],
        "review_type": "unknown",
    }
