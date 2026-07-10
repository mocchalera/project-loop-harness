from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from pcl.cli import main
from pcl.commands import create_goal
from pcl.db import connect, connect_mutation
from pcl.errors import ProjectionPendingError
from pcl.events import append_event
from pcl.migrations import apply_migrations
import pcl.migrations as migrations_module
import pcl.outbox as outbox_module
from pcl.outbox import project_pending_events
from pcl.paths import ProjectPaths


BASELINE_DB = Path("tests/fixtures/v0.3.1-baseline/db/v0.3.0-schema-7.sqlite3")


def _init(root: Path) -> ProjectPaths:
    assert main(["init", "--target", str(root), "--json"]) == 0
    return ProjectPaths(root=root.resolve())


def _event_rows(db_path: Path) -> list[dict[str, object]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
            FROM events ORDER BY sequence
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _legacy_jsonl_from_schema7_db(db_path: Path) -> bytes:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, event_type, entity_type, entity_id, payload_json, created_at
            FROM events ORDER BY rowid
            """
        ).fetchall()
    finally:
        conn.close()
    lines = []
    for row in rows:
        record = {
            "id": row["id"],
            "event_type": row["event_type"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=False))
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def _schema7_project(root: Path) -> ProjectPaths:
    paths = ProjectPaths(root=root.resolve())
    paths.loop_dir.mkdir(parents=True)
    shutil.copy2(BASELINE_DB, paths.db_path)
    paths.events_path.write_bytes(_legacy_jsonl_from_schema7_db(paths.db_path))
    return paths


def _insert_goal_pending(paths: ProjectPaths, goal_id: str, title: str) -> str:
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO goals(
              id, title, status, completion_json, stop_conditions_json, budget_json,
              created_at, updated_at
            ) VALUES (?, ?, 'open', '{}', '{}', '{}', 'now', 'now')
            """,
            (goal_id, title),
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="goal_created",
            entity_type="goal",
            entity_id=goal_id,
            payload={"title": title},
        )
        conn.commit()
        return event_id
    finally:
        conn.close()


def test_rollback_leaves_domain_event_outbox_and_jsonl_unchanged(tmp_path: Path) -> None:
    paths = _init(tmp_path)
    before_jsonl = paths.events_path.read_bytes()
    before_event_count = len(_event_rows(paths.db_path))

    conn = connect_mutation(paths)
    try:
        conn.execute(
            """
            INSERT INTO goals(
              id, title, status, completion_json, stop_conditions_json, budget_json,
              created_at, updated_at
            ) VALUES ('G-ROLLBACK', 'rollback', 'open', '{}', '{}', '{}', 'now', 'now')
            """
        )
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="goal_created",
            entity_type="goal",
            entity_id="G-ROLLBACK",
            payload={"title": "rollback"},
        )
        conn.rollback()
    finally:
        conn.close()

    check = connect(paths.db_path)
    try:
        assert check.execute("SELECT 1 FROM goals WHERE id = 'G-ROLLBACK'").fetchone() is None
        assert check.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone() is None
        assert check.execute(
            "SELECT 1 FROM outbox_records WHERE event_id = ?", (event_id,)
        ).fetchone() is None
    finally:
        check.close()
    assert len(_event_rows(paths.db_path)) == before_event_count
    assert paths.events_path.read_bytes() == before_jsonl


def test_commit_survives_projector_failure_and_reports_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _init(tmp_path)
    before_jsonl = paths.events_path.read_bytes()

    def fail_append(*args, **kwargs):
        raise OSError("injected projector failure")

    monkeypatch.setattr(outbox_module, "_append_or_match", fail_append)
    with pytest.raises(ProjectionPendingError) as raised:
        create_goal(paths, title="committed despite projector failure")

    details = raised.value.details
    assert details["committed"] is True
    assert details["projection"] == "pending"
    assert details["pending_count"] == 1
    assert details["first_pending_sequence"] is not None
    assert "do not retry" in str(details["safe_next_action"])
    assert paths.events_path.read_bytes() == before_jsonl

    conn = connect(paths.db_path)
    try:
        goal = conn.execute(
            "SELECT id FROM goals WHERE title = 'committed despite projector failure'"
        ).fetchone()
        assert goal is not None
        row = conn.execute(
            """
            SELECT events.id, outbox_records.status, outbox_records.attempts
            FROM events JOIN outbox_records ON outbox_records.event_id = events.id
            WHERE events.entity_id = ?
            """,
            (goal["id"],),
        ).fetchone()
        assert dict(row) == {"id": row["id"], "status": "retry_wait", "attempts": 1}
    finally:
        conn.close()


def test_retry_after_fsync_before_delivered_does_not_duplicate(
    tmp_path: Path,
) -> None:
    paths = _init(tmp_path)
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="fault_test",
            entity_type="system",
            entity_id="fault:fsync",
            payload={"value": 1},
        )
        conn.commit()
    finally:
        conn.close()
    def crash(point: str) -> None:
        if point == "after_jsonl_fsync_before_delivered_commit":
            raise RuntimeError("simulated process crash")

    with pytest.raises(RuntimeError, match="simulated process crash"):
        project_pending_events(paths, fault=crash)
    first_count = sum(
        1
        for line in paths.events_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["id"] == event_id
    )
    assert first_count == 1

    result = project_pending_events(paths)
    assert result.ok is True
    second_count = sum(
        1
        for line in paths.events_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["id"] == event_id
    )
    assert second_count == 1
    conn = connect(paths.db_path)
    try:
        assert conn.execute(
            "SELECT status FROM outbox_records WHERE event_id = ?", (event_id,)
        ).fetchone()["status"] == "delivered"
    finally:
        conn.close()


def test_mismatch_is_poison_and_stops_later_projection(
    tmp_path: Path,
) -> None:
    paths = _init(tmp_path)
    first_id = "G-PENDING-1"
    second_id = "G-PENDING-2"
    _insert_goal_pending(paths, first_id, "first pending")
    _insert_goal_pending(paths, second_id, "second pending")
    with paths.events_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"id": "EV-UNKNOWN"}) + "\n")

    result = project_pending_events(paths)
    assert result.projection == "failed_needs_review"
    conn = connect(paths.db_path)
    try:
        statuses = {
            row["entity_id"]: row["status"]
            for row in conn.execute(
                """
                SELECT events.entity_id, outbox_records.status
                FROM events JOIN outbox_records ON outbox_records.event_id = events.id
                WHERE events.entity_id IN (?, ?)
                """,
                (first_id, second_id),
            )
        }
        assert statuses == {first_id: "failed_needs_review", second_id: "pending"}
    finally:
        conn.close()


def test_schema7_baseline_upgrade_preserves_legacy_prefix_and_accepts_new_event(
    tmp_path: Path,
) -> None:
    paths = _schema7_project(tmp_path)
    legacy = paths.events_path.read_bytes()

    result = apply_migrations(paths)
    assert [migration.version for migration in result.applied] == [8]
    assert paths.events_path.read_bytes().startswith(legacy)

    conn = connect(paths.db_path)
    try:
        sequences = [row["sequence"] for row in conn.execute("SELECT sequence FROM events ORDER BY sequence")]
        assert sequences == list(range(1, len(sequences) + 1))
        legacy_statuses = conn.execute(
            """
            SELECT outbox_records.status
            FROM outbox_records JOIN events ON events.id = outbox_records.event_id
            WHERE events.sequence <= 8 ORDER BY events.sequence
            """
        ).fetchall()
        assert {row["status"] for row in legacy_statuses} == {"delivered"}
    finally:
        conn.close()

    goal_id = create_goal(paths, title="post migration")
    records = [json.loads(line) for line in paths.events_path.read_text().splitlines()]
    assert any(record.get("entity_id") == goal_id for record in records)


def test_migration_statement_failure_rolls_back_schema_metadata_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _schema7_project(tmp_path)
    original = migrations_module._execute_sql_script

    def fail_during_008(conn: sqlite3.Connection, sql: str) -> None:
        if "events_pre_outbox_008" not in sql:
            original(conn, sql)
            return
        conn.execute("ALTER TABLE events RENAME TO events_pre_outbox_008")
        raise RuntimeError("between migration statements")

    monkeypatch.setattr(migrations_module, "_execute_sql_script", fail_during_008)
    with pytest.raises(RuntimeError, match="between migration statements"):
        apply_migrations(paths)

    conn = connect(paths.db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        assert "sequence" not in columns
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'outbox_records'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 8"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM events WHERE entity_id = 'migration:008_event_outbox'"
        ).fetchone() is None
    finally:
        conn.close()


def test_read_only_commands_do_not_change_outbox(tmp_path: Path, capsys) -> None:
    paths = _init(tmp_path)
    conn = connect(paths.db_path)
    try:
        before = [tuple(row) for row in conn.execute("SELECT * FROM outbox_records ORDER BY event_id")]
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    capsys.readouterr()

    conn = connect(paths.db_path)
    try:
        after = [tuple(row) for row in conn.execute("SELECT * FROM outbox_records ORDER BY event_id")]
    finally:
        conn.close()
    assert after == before


def test_concurrent_mutations_keep_contiguous_event_order(tmp_path: Path) -> None:
    paths = _init(tmp_path)
    before_count = len(_event_rows(paths.db_path))
    with ThreadPoolExecutor(max_workers=4) as executor:
        goal_ids = list(executor.map(lambda n: create_goal(paths, title=f"concurrent {n}"), range(8)))
    assert len(set(goal_ids)) == 8

    rows = _event_rows(paths.db_path)
    assert [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
    jsonl = [json.loads(line) for line in paths.events_path.read_text().splitlines()]
    assert [record["sequence"] for record in jsonl] == list(range(1, len(jsonl) + 1))
    assert len(rows) == len(jsonl) == before_count + 8


def test_fsync_occurs_before_delivered_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _init(tmp_path)
    _insert_goal_pending(paths, "G-FSYNC", "fsync ordering")
    calls: list[str] = []
    original_fsync = outbox_module.os.fsync
    original_delivered = outbox_module._mark_delivered

    def tracking_fsync(fd: int) -> None:
        calls.append("fsync")
        original_fsync(fd)

    def tracking_delivered(db_path: Path, outbox_id: str) -> None:
        calls.append("delivered")
        original_delivered(db_path, outbox_id)

    monkeypatch.setattr(outbox_module.os, "fsync", tracking_fsync)
    monkeypatch.setattr(outbox_module, "_mark_delivered", tracking_delivered)
    assert project_pending_events(paths).ok is True
    assert calls == ["fsync", "delivered"]
