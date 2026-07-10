from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcl.cli import main
from pcl.db import connect


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "goals": int(conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]),
            "tasks": int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]),
            "evidence": int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "outbox": int(conn.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0]),
            "jsonl": len(
                (root / ".project-loop" / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ),
        }
    finally:
        conn.close()


def test_start_help_contract_and_profile_is_rejected(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["start", "--help"])
    assert help_exit.value.code == 0
    help_output = capsys.readouterr().out
    assert "usage: pcl start [-h] [--dry-run] [--no-init] [--new]" in help_output
    assert "intent" in help_output
    assert "--profile" not in help_output

    with pytest.raises(SystemExit) as profile_exit:
        main(["start", "Ship it", "--profile", "direct"])
    assert profile_exit.value.code == 2
    assert "unrecognized arguments: --profile direct" in capsys.readouterr().err


def test_start_uninitialized_dry_run_lists_init_and_state_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "new-project"

    assert main(["--root", str(root), "start", "Fix login timeout", "--dry-run", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["status"] == "planned"
    assert payload["mutated"] is False
    assert payload["result"]["project_initialized"] is False
    changes = payload["result"]["initialization"]["changes"]
    assert any(change["path"] == ".project-loop/project.db" for change in changes)
    assert any(change["path"] == "pcl.yaml" for change in changes)
    assert any(
        change["path"] == ".agents/skills/project-control-loop/SKILL.md"
        for change in changes
    )
    assert [entity["type"] for entity in payload["result"]["planned_entities"]] == [
        "goal",
        "task",
        "evidence",
        "event",
    ]
    assert not root.exists()


def test_start_initialized_dry_run_preserves_database_and_audit_counts(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    before = _counts(tmp_path)

    assert main(["--root", str(tmp_path), "start", "Plan only", "--dry-run", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["status"] == "planned"
    assert payload["result"]["initialization"] is None
    assert _counts(tmp_path) == before


def test_start_no_init_stops_without_creating_project(tmp_path: Path, capsys) -> None:
    root = tmp_path / "new-project"

    assert main(["--root", str(root), "start", "Do work", "--no-init", "--json"]) == 3
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "not_initialized"
    assert not root.exists()


def test_start_apply_auto_initializes_and_records_active_target_receipt_and_event(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"

    assert main(["--root", str(root), "start", "Fix login timeout", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["contract_version"] == "pcl-start/v1"
    assert payload["status"] == "started"
    assert payload["mutated"] is True
    assert payload["result"]["project_initialized"] is True
    assert payload["result"]["created_ids"]["goal"] == "G-0001"
    assert payload["result"]["created_ids"]["task"] == "T-0001"
    assert payload["result"]["created_ids"]["evidence"] == "E-0001"
    assert payload["result"]["target"] == {"type": "task", "id": "T-0001"}
    assert payload["next_actions"] == [
        {
            "command": "pcl context pack --task T-0001 --json",
            "target": {"type": "task", "id": "T-0001"},
            "text": "Review the task context and begin the requested work.",
        }
    ]

    assert main(["--root", str(root), "task", "read", "T-0001", "--json"]) == 0
    task = _json_output(capsys)["task"]
    assert task["title"] == "Fix login timeout"
    assert task["related_goal_id"] == "G-0001"
    assert task["status"] == "todo"

    conn = connect(root / ".project-loop" / "project.db")
    try:
        evidence = conn.execute(
            "SELECT type, path, command, summary FROM evidence WHERE id = 'E-0001'"
        ).fetchone()
        event = conn.execute(
            "SELECT event_type, entity_type, entity_id, payload_json FROM events "
            "WHERE event_type = 'work_started'"
        ).fetchone()
    finally:
        conn.close()
    persisted_receipt = dict(payload["result"]["receipt"])
    persisted_receipt.pop("evidence_id")
    persisted_receipt.pop("event_id")
    assert dict(evidence) | {"summary": json.loads(evidence["summary"])} == {
        "type": "start-receipt/v1",
        "path": "inline:start:T-0001",
        "command": "pcl start",
        "summary": persisted_receipt,
    }
    event_payload = json.loads(event["payload_json"])
    assert event["event_type"] == "work_started"
    assert event["entity_type"] == "task"
    assert event["entity_id"] == "T-0001"
    assert event_payload["evidence_id"] == "E-0001"
    assert event_payload["receipt"]["intent"] == "Fix login timeout"
    assert _counts(root)["events"] == _counts(root)["jsonl"]


def test_start_is_idempotent_for_active_work_and_new_is_explicit(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "start", "First intent", "--json"]) == 0
    _json_output(capsys)
    before = _counts(tmp_path)

    assert main(["--root", str(tmp_path), "start", "Second intent", "--json"]) == 0
    duplicate = _json_output(capsys)
    assert duplicate["status"] == "active_work_exists"
    assert duplicate["mutated"] is False
    assert duplicate["result"]["created_ids"] == {}
    assert "--new" in duplicate["next_actions"][0]["text"]
    assert _counts(tmp_path) == before

    assert main(["--root", str(tmp_path), "start", "Second intent", "--new", "--json"]) == 0
    created = _json_output(capsys)
    assert created["status"] == "started"
    assert created["result"]["created_ids"]["goal"] == "G-0002"
    assert created["result"]["created_ids"]["task"] == "T-0002"
    assert _counts(tmp_path)["goals"] == before["goals"] + 1
    assert _counts(tmp_path)["tasks"] == before["tasks"] + 1


@pytest.mark.parametrize(
    "intent",
    [
        "Windows path C:\\src\\app.py を直す",
        "Unicode: 認証を改善する 🚂",
        "Literal shell text: $(touch SHOULD_NOT_EXIST); `whoami`; ../secrets",
    ],
)
def test_start_preserves_intent_as_literal_text(
    tmp_path: Path,
    capsys,
    intent: str,
) -> None:
    root = tmp_path / "project"
    _init(root, capsys)

    assert main(["--root", str(root), "start", intent, "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["result"]["intent"] == intent
    assert payload["result"]["receipt"]["intent"] == intent
    assert main(["--root", str(root), "task", "read", "T-0001", "--json"]) == 0
    assert _json_output(capsys)["task"]["title"] == intent
    assert not (root / "SHOULD_NOT_EXIST").exists()


def test_start_json_matches_stable_snapshot(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "start", "Snapshot intent", "--json"]) == 0
    payload = _json_output(capsys)
    payload["result"]["created_ids"]["event"] = "<event-id>"
    payload["result"]["receipt"]["event_id"] = "<event-id>"
    payload["result"]["receipt"]["generated_at"] = "<generated-at>"
    payload["result"]["receipt"]["repository_revision"] = "<repository-revision>"

    expected = json.loads((FIXTURE_ROOT / "start_initialized_v1.json").read_text(encoding="utf-8"))
    assert payload == expected


def test_start_skill_provenance_is_canonical_linked_and_anchored(tmp_path: Path, capsys) -> None:
    skill_a = tmp_path / "skills" / "alpha" / "SKILL.md"
    skill_b = tmp_path / "skills" / "beta" / "SKILL.md"
    skill_a.parent.mkdir(parents=True)
    skill_b.parent.mkdir(parents=True)
    skill_a.write_text("---\nname: alpha-skill\n---\nA\n", encoding="utf-8")
    skill_b.write_bytes(b"B\r\n")
    root = tmp_path / "project"

    assert main([
        "--root", str(root), "start", "Provenance", "--skill", str(skill_a),
        "--skill", str(skill_b), "--json",
    ]) == 0
    payload = _json_output(capsys)
    provenance = payload["result"]["provenance"]
    artifact = root / provenance["path"]
    raw = artifact.read_bytes()
    assert raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest() == provenance["artifact_sha256"]
    document = json.loads(raw)
    assert [item["name"] for item in document["skills"]] == ["alpha-skill", "beta"]
    assert document["target"] == {"type": "task", "id": "T-0001"}

    conn = connect(root / ".project-loop" / "project.db")
    try:
        evidence = conn.execute("SELECT type, path, summary FROM evidence WHERE id = ?", (provenance["evidence_id"],)).fetchone()
        link = conn.execute("SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ?", (provenance["evidence_id"],)).fetchone()
        event = conn.execute("SELECT payload_json FROM events WHERE event_type = 'work_started'").fetchone()
    finally:
        conn.close()
    assert evidence["type"] == "execution_provenance"
    assert str(skill_a.resolve()) not in evidence["summary"]
    assert dict(link) == {"target_type": "task", "target_id": "T-0001", "link_role": "execution_provenance"}
    assert json.loads(event["payload_json"])["execution_provenance"]["artifact_sha256"] == provenance["artifact_sha256"]


def test_start_skill_dry_run_hashes_without_creating_project_and_rejects_duplicates(tmp_path: Path, capsys) -> None:
    skill = tmp_path / "one" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("hello", encoding="utf-8")
    root = tmp_path / "project"
    assert main(["--root", str(root), "start", "Plan", "--skill", str(skill), "--dry-run", "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["result"]["planned_provenance"][0]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert payload["result"]["planned_provenance"] == [{
        "name": "one",
        "path_basename": "SKILL.md",
        "path_scope": "outside_project",
        "sha256": hashlib.sha256(b"hello").hexdigest(),
    }]
    assert str(skill.resolve()) not in json.dumps(payload)
    assert not root.exists()

    assert main(["--root", str(root), "start", "Nope", "--skill", str(skill), "--skill", str(skill.parent / "." / "SKILL.md"), "--json"]) == 2
    error = _json_output(capsys)
    assert error["error"]["code"] == "skill_path_duplicate"
    assert str(skill.resolve()) not in json.dumps(error)
    assert not root.exists()
