from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.paths import resolve_paths
from pcl.start import start_work
from pcl.start_retry import load_compatible_start_retry


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


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
    assert "usage: pcl start" in help_output
    assert "--goal GOAL" in help_output
    assert "--task TASK" in help_output
    assert "intent" in help_output
    assert "--profile" not in help_output

    with pytest.raises(SystemExit) as profile_exit:
        main(["start", "Ship it", "--profile", "direct"])
    assert profile_exit.value.code == 2
    assert "unrecognized arguments: --profile direct" in capsys.readouterr().err


def test_start_attaches_existing_task_without_duplicate_entities_and_activates_atomically(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Existing goal"]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Existing task",
        "--goal", "G-0001",
    ]) == 0
    capsys.readouterr()
    before = _counts(tmp_path)

    import pcl.start as start_module

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("receipt failure")

    monkeypatch.setattr(start_module, "record_inline_evidence", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt failure"):
        start_work(
            resolve_paths(tmp_path),
            intent="Attach without drift",
            task_id="T-0001",
        )

    assert _counts(tmp_path) == before
    assert main(["--root", str(tmp_path), "task", "read", "T-0001", "--json"]) == 0
    assert _json_output(capsys)["task"]["status"] == "todo"

    monkeypatch.undo()
    assert main([
        "--root", str(tmp_path), "start", "Attach without drift",
        "--task", "T-0001", "--json",
    ]) == 0
    payload = _json_output(capsys)

    assert payload["status"] == "started"
    assert payload["result"]["target"] == {"type": "task", "id": "T-0001"}
    assert "goal" not in payload["result"]["created_ids"]
    assert "task" not in payload["result"]["created_ids"]
    assert payload["result"]["receipt"]["created_ids"] == {}
    assert payload["next_actions"][0]["command"] == (
        "pcl context pack --task T-0001 --json"
    )
    assert _counts(tmp_path)["goals"] == before["goals"]
    assert _counts(tmp_path)["tasks"] == before["tasks"]

    assert main(["--root", str(tmp_path), "task", "read", "T-0001", "--json"]) == 0
    assert _json_output(capsys)["task"]["status"] == "in_progress"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        events = conn.execute(
            "SELECT event_type, entity_id FROM events "
            "WHERE entity_id = 'T-0001' ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    assert [dict(row) for row in events[-2:]] == [
        {"event_type": "task_status_changed", "entity_id": "T-0001"},
        {"event_type": "work_started", "entity_id": "T-0001"},
    ]


def test_start_active_task_exact_retry_reuses_anchored_receipt_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root", str(tmp_path), "goal", "create", "--title", "Existing goal",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Existing task",
        "--goal", "G-0001",
    ]) == 0
    capsys.readouterr()
    command = [
        "--root", str(tmp_path), "start", "Attach retry identity",
        "--task", "T-0001", "--json",
    ]

    assert main(command) == 0
    first = _json_output(capsys)
    assert first["status"] == "started"
    assert first["mutated"] is True
    assert first["result"]["receipt"]["request_identity_sha256"].startswith(
        "sha256:"
    )
    before_retry = _counts(tmp_path)

    assert main(command) == 0
    retry = _json_output(capsys)

    assert retry["status"] == "already_started"
    assert retry["mutated"] is False
    assert retry["result"]["idempotent"] is True
    assert retry["result"]["created_ids"] == {}
    assert retry["result"]["reused_ids"] == {
        "event": first["result"]["created_ids"]["event"],
        "evidence": first["result"]["created_ids"]["evidence"],
    }
    assert retry["result"]["receipt"] == first["result"]["receipt"]
    assert _counts(tmp_path) == before_retry

    assert main([
        "--root", str(tmp_path), "start", "Changed attach intent",
        "--task", "T-0001", "--json",
    ]) == 0
    changed = _json_output(capsys)
    assert changed["status"] == "started"
    assert changed["mutated"] is True
    assert changed["result"]["created_ids"]["event"] != (
        first["result"]["created_ids"]["event"]
    )
    assert _counts(tmp_path)["events"] == before_retry["events"] + 1
    assert _counts(tmp_path)["evidence"] == before_retry["evidence"] + 1


def test_start_active_task_retry_identity_covers_head_and_skill_hashes(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    skill = tmp_path / "skills" / "retry" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: retry\n---\nfirst\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("one\n", encoding="utf-8")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "pcl@example.test")
    _git(tmp_path, "config", "user.name", "PCL Test")
    _git(tmp_path, "add", ".gitignore", "README.md", "skills/retry/SKILL.md")
    _git(tmp_path, "commit", "-m", "baseline")
    assert main([
        "--root", str(tmp_path), "goal", "create", "--title", "Existing goal",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Existing task",
        "--goal", "G-0001",
    ]) == 0
    capsys.readouterr()
    command = [
        "--root", str(tmp_path), "start", "Attach with provenance",
        "--task", "T-0001", "--skill", str(skill), "--json",
    ]

    assert main(command) == 0
    first = _json_output(capsys)
    before_retry = _counts(tmp_path)
    assert main(command) == 0
    retry = _json_output(capsys)
    assert retry["status"] == "already_started"
    assert retry["result"]["provenance"] == first["result"]["provenance"]
    assert _counts(tmp_path) == before_retry

    skill.write_text("---\nname: retry\n---\nsecond\n", encoding="utf-8")
    assert main(command) == 0
    skill_changed = _json_output(capsys)
    assert skill_changed["status"] == "started"
    assert skill_changed["mutated"] is True

    readme.write_text("two\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md", "skills/retry/SKILL.md")
    _git(tmp_path, "commit", "-m", "change retry identity")
    assert main(command) == 0
    head_changed = _json_output(capsys)
    assert head_changed["status"] == "started"
    assert head_changed["mutated"] is True


def test_start_active_task_retry_fails_closed_for_broken_evidence_anchor(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root", str(tmp_path), "goal", "create", "--title", "Existing goal",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Existing task",
        "--goal", "G-0001",
    ]) == 0
    capsys.readouterr()
    command = [
        "--root", str(tmp_path), "start", "Anchored retry",
        "--task", "T-0001", "--json",
    ]

    assert main(command) == 0
    first = _json_output(capsys)
    before_retry = _counts(tmp_path)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE evidence SET type = 'adhoc_artifact' WHERE id = ?",
            (first["result"]["created_ids"]["evidence"],),
        )
        conn.commit()
    finally:
        conn.close()

    assert main(command) == 0
    retry = _json_output(capsys)

    assert retry["status"] == "started"
    assert retry["mutated"] is True
    assert "idempotent" not in retry["result"]
    assert retry["result"]["created_ids"]["event"] != (
        first["result"]["created_ids"]["event"]
    )
    assert retry["result"]["created_ids"]["evidence"] != (
        first["result"]["created_ids"]["evidence"]
    )
    assert _counts(tmp_path)["events"] == before_retry["events"] + 1
    assert _counts(tmp_path)["evidence"] == before_retry["evidence"] + 1


def test_load_start_retry_rejects_missing_receipt_anchor(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main([
        "--root", str(tmp_path), "goal", "create", "--title", "Existing goal",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Existing task",
        "--goal", "G-0001",
    ]) == 0
    capsys.readouterr()
    command = [
        "--root", str(tmp_path), "start", "Anchored retry",
        "--task", "T-0001", "--json",
    ]

    assert main(command) == 0
    first = _json_output(capsys)
    receipt = first["result"]["receipt"]
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT payload_json FROM events WHERE id = ?",
            (first["result"]["created_ids"]["event"],),
        ).fetchone()
        payload = json.loads(str(row["payload_json"]))
        payload.pop("receipt")
        conn.execute(
            "UPDATE events SET payload_json = ? WHERE id = ?",
            (
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                first["result"]["created_ids"]["event"],
            ),
        )
        conn.commit()

        assert load_compatible_start_retry(
            resolve_paths(tmp_path),
            conn,
            task_id="T-0001",
            request_identity_sha256=receipt["request_identity_sha256"],
            repository_revision=receipt["repository_revision"],
            skills=[],
            receipt_contract_version="pcl-start/v1",
        ) is None
    finally:
        conn.close()


def test_start_goal_attach_reuses_goal_and_creates_only_active_child(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Existing goal"]) == 0
    capsys.readouterr()
    before = _counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "start", "Focused child work",
        "--goal", "G-0001", "--json",
    ]) == 0
    payload = _json_output(capsys)

    assert payload["result"]["created_ids"]["task"] == "T-0001"
    assert "goal" not in payload["result"]["created_ids"]
    assert payload["result"]["receipt"]["created_ids"] == {"task": "T-0001"}
    assert payload["result"]["target"] == {"type": "task", "id": "T-0001"}
    assert _counts(tmp_path)["goals"] == before["goals"]
    assert _counts(tmp_path)["tasks"] == before["tasks"] + 1
    assert main(["--root", str(tmp_path), "task", "read", "T-0001", "--json"]) == 0
    task = _json_output(capsys)["task"]
    assert task["related_goal_id"] == "G-0001"
    assert task["status"] == "in_progress"


def test_start_attach_fails_closed_for_conflicting_missing_and_terminal_targets(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Existing goal"]) == 0
    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Terminal task",
        "--goal", "G-0001",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "task", "status", "T-0001", "cancelled",
        "--reason", "Closed",
    ]) == 0
    capsys.readouterr()
    before = _counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "start", "Conflict",
        "--goal", "G-0001", "--task", "T-0001", "--json",
    ]) == 2
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "start", "Missing",
        "--task", "T-9999", "--json",
    ]) == 2
    missing = _json_output(capsys)
    assert missing["error"]["details"]["target"] == "T-9999"
    assert main([
        "--root", str(tmp_path), "start", "Terminal",
        "--task", "T-0001", "--json",
    ]) == 2
    terminal = _json_output(capsys)
    assert terminal["error"]["details"] == {
        "target": "T-0001",
        "target_type": "task",
        "status": "cancelled",
    }
    assert _counts(tmp_path) == before


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
    assert task["status"] == "in_progress"

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


def test_start_auto_initialization_detects_node_project_commands(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "node-project"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "agent-ready-node-app",
                "scripts": {
                    "test": "node --test",
                    "build": "node --check src/main.js",
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(["--root", str(root), "start", "Add a puzzle mode", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["status"] == "started"
    assert payload["result"]["project_initialized"] is True
    config = (root / "pcl.yaml").read_text(encoding="utf-8")
    assert 'name: "agent-ready-node-app"' in config
    assert 'type: "node"' in config
    assert 'test: "npm run test"' in config
    assert 'build: "npm run build"' in config


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
    assert created["next_actions"][0]["command"] == "pcl context pack --task T-0002 --json"
    assert created["next_actions"][0]["target"] == {"type": "task", "id": "T-0002"}
    assert _counts(tmp_path)["goals"] == before["goals"] + 1
    assert _counts(tmp_path)["tasks"] == before["tasks"] + 1

    assert main(["--root", str(tmp_path), "start", "Third intent", "--json"]) == 0
    ambiguous = _json_output(capsys)
    assert ambiguous["status"] == "active_work_exists"
    assert ambiguous["next_actions"][0]["command"] is None
    assert ambiguous["next_actions"][0]["target"] is None


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
