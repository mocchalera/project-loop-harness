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


def _add_feature(root: Path, capsys, *, name: str, surface: str = "cli:pcl") -> str:
    assert main([
        "--root",
        str(root),
        "feature",
        "add",
        "--name",
        name,
        "--surface",
        surface,
        "--json",
    ]) == 0
    return str(_json_output(capsys)["id"])


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


def test_feature_list_and_read_return_deterministic_json(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    first_id = _add_feature(tmp_path, capsys, name="Login", surface="ui:/login")
    second_id = _add_feature(tmp_path, capsys, name="Dashboard", surface="ui:/dashboard")

    assert main(["--root", str(tmp_path), "feature", "list", "--json"]) == 0
    listed = _json_output(capsys)

    assert listed["ok"] is True
    assert [feature["id"] for feature in listed["features"]] == [first_id, second_id]
    assert listed["features"][0] == {
        "confidence": "medium",
        "created_at": listed["features"][0]["created_at"],
        "description": "",
        "id": first_id,
        "name": "Login",
        "status": "discovered",
        "surface": "ui:/login",
        "updated_at": listed["features"][0]["updated_at"],
    }

    assert main(["--root", str(tmp_path), "feature", "read", first_id, "--json"]) == 0
    read_payload = _json_output(capsys)

    assert read_payload["ok"] is True
    assert read_payload["feature"]["id"] == first_id
    assert read_payload["feature"]["name"] == "Login"
    assert read_payload["feature"]["surface"] == "ui:/login"


def test_feature_list_filters_by_status(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    passing_id = _add_feature(tmp_path, capsys, name="Passing feature")
    discovered_id = _add_feature(tmp_path, capsys, name="Discovered feature")

    assert main([
        "--root",
        str(tmp_path),
        "story",
        "draft",
        "--feature",
        passing_id,
        "--actor",
        "operator",
        "--goal",
        "inspect features",
        "--expected-behavior",
        "feature can be listed and read",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "story",
        "review",
        "US-0001",
        "--summary",
        "Ready",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "story",
        "approve",
        "US-0001",
        "--summary",
        "Approved",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "test",
        "plan",
        "--feature",
        passing_id,
        "--story",
        "US-0001",
        "--type",
        "unit",
        "--scenario",
        "Feature CLI inspection",
        "--expected",
        "Feature can be listed and read",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root",
        str(tmp_path),
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Feature CLI inspection passed",
        "--evidence",
        "pytest tests/test_features.py passed",
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "feature", "list", "--status", "passing", "--json"]) == 0
    passing = _json_output(capsys)
    assert [feature["id"] for feature in passing["features"]] == [passing_id]

    assert main(["--root", str(tmp_path), "feature", "list", "--status", "discovered", "--json"]) == 0
    discovered = _json_output(capsys)
    assert [feature["id"] for feature in discovered["features"]] == [discovered_id]


def test_feature_read_and_filter_errors_are_typed_json(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "feature", "list", "--status", "unknown", "--json"]) == 2
    invalid_status = _json_output(capsys)
    assert invalid_status["error"]["code"] == "invalid_input"
    assert invalid_status["error"]["details"]["allowed"] == [
        "discovered",
        "done",
        "needs_fix",
        "needs_test",
        "passing",
        "specified",
        "waived",
    ]

    assert main(["--root", str(tmp_path), "feature", "read", "F-9999", "--json"]) == 2
    missing = _json_output(capsys)
    assert missing["error"]["code"] == "invalid_input"
    assert missing["error"]["details"]["feature_id"] == "F-9999"


def test_feature_status_plain_error_lists_allowed_values(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_id = _add_feature(tmp_path, capsys, name="Migration", surface="cli:pcl migrate")

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "implemented",
        "--summary",
        "Invalid",
        "--evidence",
        "Invalid status",
    ]) == 2
    captured = capsys.readouterr()

    assert "ERROR: Invalid feature status: implemented" in captured.err
    assert "Allowed values: discovered, done, needs_fix, needs_test, passing, specified, waived" in captured.err


def test_feature_status_updates_with_evidence_and_typed_errors(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_id = _add_feature(tmp_path, capsys, name="Migration", surface="cli:pcl migrate")

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "passing",
        "--summary",
        "Migration flow verified",
        "--evidence",
        "pytest tests/test_migrations.py passed",
        "--json",
    ]) == 0
    result = _json_output(capsys)
    assert result == {
        "changed": True,
        "evidence_id": "E-0001",
        "feature_id": feature_id,
        "ok": True,
        "previous_status": "discovered",
        "status": "passing",
        "summary": "Migration flow verified",
    }

    assert main(["--root", str(tmp_path), "feature", "read", feature_id, "--json"]) == 0
    feature = _json_output(capsys)["feature"]
    assert feature["status"] == "passing"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        evidence = conn.execute("SELECT type, path, summary FROM evidence WHERE id = 'E-0001'").fetchone()
        event = conn.execute(
            """
            SELECT event_type, payload_json
            FROM events
            WHERE event_type = 'feature_status_updated'
            """
        ).fetchone()
    finally:
        conn.close()
    assert dict(evidence) == {
        "path": f"inline:feature/{feature_id}/status",
        "summary": "pytest tests/test_migrations.py passed",
        "type": "feature_status",
    }
    payload = json.loads(event["payload_json"])
    assert payload == {
        "evidence": "pytest tests/test_migrations.py passed",
        "evidence_id": "E-0001",
        "previous_status": "discovered",
        "source": "manual",
        "status": "passing",
        "summary": "Migration flow verified",
    }

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "done",
        "--summary",
        "Missing evidence",
        "--json",
    ]) == 2
    missing_evidence = _json_output(capsys)
    assert missing_evidence["error"]["code"] == "invalid_input"
    assert "--evidence is required" in missing_evidence["error"]["message"]

    before_no_op = _audit_counts(tmp_path)
    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "passing",
        "--json",
    ]) == 0
    no_op = _json_output(capsys)
    assert no_op == {
        "changed": False,
        "evidence_recorded": False,
        "feature_id": feature_id,
        "ok": True,
        "previous_status": "passing",
        "status": "passing",
    }
    assert _audit_counts(tmp_path) == before_no_op

    for _ in range(2):
        assert main([
            "--root",
            str(tmp_path),
            "feature",
            "status",
            feature_id,
            "--status",
            "passing",
            "--json",
        ]) == 0
        assert _json_output(capsys) == no_op
        assert _audit_counts(tmp_path) == before_no_op

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "passing",
        "--summary",
        "No change",
        "--evidence",
        "Already passing",
        "--json",
    ]) == 0
    with_evidence = _json_output(capsys)
    assert with_evidence["changed"] is False
    assert with_evidence["evidence_recorded"] is False
    assert _audit_counts(tmp_path) == before_no_op

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "passing",
        "--summary",
        "No change",
        "--evidence",
        "Already passing",
    ]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"Feature {feature_id} already passing; no change recorded.\n"
    assert _audit_counts(tmp_path) == before_no_op

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        feature_id,
        "--status",
        "unknown",
        "--summary",
        "Invalid",
        "--evidence",
        "Invalid status",
        "--json",
    ]) == 2
    invalid_status = _json_output(capsys)
    assert invalid_status["error"]["code"] == "invalid_input"
    assert invalid_status["error"]["details"]["allowed"] == [
        "discovered",
        "done",
        "needs_fix",
        "needs_test",
        "passing",
        "specified",
        "waived",
    ]

    assert main([
        "--root",
        str(tmp_path),
        "feature",
        "status",
        "F-9999",
        "--status",
        "passing",
        "--summary",
        "Unknown",
        "--evidence",
        "Unknown feature",
        "--json",
    ]) == 2
    unknown = _json_output(capsys)
    assert unknown["error"]["code"] == "invalid_input"
    assert unknown["error"]["details"] == {"feature_id": "F-9999"}
