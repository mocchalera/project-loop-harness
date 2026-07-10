from __future__ import annotations

import errno
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

from pcl.audit import audit_check
from pcl.commands import create_goal
from pcl.db import connect, connect_mutation
import pcl.db as db_module
from pcl.errors import DataStoreError
from pcl.events import append_event
from pcl.evidence import record_adhoc_evidence
from pcl.locks import AdvisoryLock
import pcl.outbox as outbox_module
from pcl.outbox import project_pending_events
from pcl.paths import ProjectPaths


BASELINE_DB = Path("tests/fixtures/v0.3.1-baseline/db/v0.3.0-schema-7.sqlite3")
FAULT_ENV_KEYS = {
    "PCL_ENABLE_TEST_FAULTS",
    "PCL_TEST_FAULT_POINT",
    "PCL_TEST_FAULT_OCCURRENCE",
    "PCL_TEST_FAULT_MARKER",
}


def _cli(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    clean_env = {key: value for key, value in os.environ.items() if key not in FAULT_ENV_KEYS}
    clean_env["PYTHONPATH"] = str(Path("src").resolve())
    if env:
        clean_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "pcl", "--root", str(root), *args, "--json"],
        cwd=Path.cwd(),
        env=clean_env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def _init(root: Path) -> ProjectPaths:
    result = subprocess.run(
        [sys.executable, "-m", "pcl", "init", "--target", str(root), "--json"],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return ProjectPaths(root=root.resolve())


def _fault_env(point: str, marker: Path) -> dict[str, str]:
    return {
        "PCL_ENABLE_TEST_FAULTS": "1",
        "PCL_TEST_FAULT_POINT": point,
        "PCL_TEST_FAULT_MARKER": str(marker),
    }


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def _write_ci_summary(name: str, payload: dict[str, object]) -> None:
    destination = os.environ.get("PCL_RELIABILITY_ARTIFACT_DIR")
    if not destination:
        return
    artifact_dir = Path(destination)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def test_fault_point_without_explicit_enable_is_inert(tmp_path: Path) -> None:
    root = tmp_path / "fault-disabled"
    _init(root)
    result = _cli(
        root,
        "goal",
        "create",
        "--title",
        "normal mutation",
        env={"PCL_TEST_FAULT_POINT": "before_sqlite_commit"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert _cli(root, "audit", "check").returncode == 0


@pytest.mark.parametrize(
    ("point", "committed"),
    [
        ("before_sqlite_commit", False),
        ("after_sqlite_commit_before_projector", True),
        ("projector_after_attempt_before_append", True),
        ("before_jsonl_append", True),
        ("after_jsonl_write_before_fsync", True),
        ("after_jsonl_fsync_before_delivered_commit", True),
    ],
)
def test_process_crash_matrix_converges(
    tmp_path: Path,
    point: str,
    committed: bool,
) -> None:
    root = tmp_path / point
    paths = _init(root)
    marker = tmp_path / f"{point}.marker.json"
    title = f"crash at {point}"

    crashed = _cli(
        root,
        "goal",
        "create",
        "--title",
        title,
        env=_fault_env(point, marker),
    )
    assert crashed.returncode != 0
    assert json.loads(marker.read_text(encoding="utf-8"))["point"] == point

    conn = connect(paths.db_path)
    try:
        goal_count = int(
            conn.execute("SELECT COUNT(*) AS n FROM goals WHERE title = ?", (title,)).fetchone()["n"]
        )
        foreign_key_violations = list(conn.execute("PRAGMA foreign_key_check"))
    finally:
        conn.close()
    assert goal_count == int(committed)
    assert foreign_key_violations == []

    checked = _cli(root, "audit", "check")
    strict_before = _cli(root, "validate", "--strict")
    report = _json(checked)
    _write_ci_summary(
        f"crash-{point}",
        {
            "fault_point": point,
            "crash_returncode": crashed.returncode,
            "audit": report,
            "validate": _json(strict_before),
        },
    )
    if not committed:
        assert checked.returncode == 0
        assert strict_before.returncode == 0
    else:
        assert checked.returncode == 6
        assert report["counts"]["anomalies_by_classification"]["repairable"] >= 1
        expected_strict = 0 if point in {
            "after_jsonl_write_before_fsync",
            "after_jsonl_fsync_before_delivered_commit",
        } else 1
        assert strict_before.returncode == expected_strict
        repaired = _cli(root, "audit", "repair", "--apply")
        assert repaired.returncode == 0, repaired.stderr or repaired.stdout

    assert _cli(root, "audit", "check").returncode == 0
    assert _cli(root, "validate", "--strict").returncode == 0
    events = [json.loads(line) for line in paths.events_path.read_text().splitlines()]
    event_ids = [event["id"] for event in events]
    assert len(event_ids) == len(set(event_ids))


def test_process_crash_during_jsonl_append_requires_reviewed_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "partial-append"
    _init(root)
    marker = tmp_path / "partial-append.marker.json"
    crashed = _cli(
        root,
        "goal",
        "create",
        "--title",
        "partial append",
        env=_fault_env("during_jsonl_append", marker),
    )
    assert crashed.returncode != 0
    assert marker.exists()
    checked = _cli(root, "audit", "check")
    assert checked.returncode == 7
    assert _cli(root, "validate", "--strict").returncode == 1
    assert _cli(root, "audit", "repair", "--apply").returncode == 7
    rebuilt = _cli(root, "audit", "rebuild-jsonl", "--from-sqlite", "--apply")
    assert rebuilt.returncode == 0, rebuilt.stderr or rebuilt.stdout
    assert _cli(root, "audit", "check").returncode == 0
    assert _cli(root, "validate", "--strict").returncode == 0


def test_process_crash_after_delivered_commit_is_clean(tmp_path: Path) -> None:
    root = tmp_path / "delivered"
    _init(root)
    marker = tmp_path / "delivered.marker.json"
    crashed = _cli(
        root,
        "goal",
        "create",
        "--title",
        "delivered before crash",
        env=_fault_env("after_outbox_delivered_commit", marker),
    )
    assert crashed.returncode != 0
    assert marker.exists()
    assert _cli(root, "audit", "check").returncode == 0
    assert _cli(root, "validate", "--strict").returncode == 0


def _legacy_jsonl(db_path: Path) -> bytes:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, event_type, entity_type, entity_id, payload_json, created_at "
            "FROM events ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    records = [
        {
            "id": row["id"],
            "event_type": row["event_type"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return ("\n".join(json.dumps(record) for record in records) + "\n").encode()


def test_process_crash_between_migration_statements_rolls_back(tmp_path: Path) -> None:
    root = tmp_path / "migration"
    paths = _init(root)
    shutil.copy2(BASELINE_DB, paths.db_path)
    paths.events_path.write_bytes(_legacy_jsonl(paths.db_path))
    marker = tmp_path / "migration.marker.json"

    crashed = _cli(
        root,
        "migrate",
        env=_fault_env("after_migration_statement", marker),
    )
    assert crashed.returncode != 0
    assert marker.exists()
    conn = connect(paths.db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        assert "sequence" not in columns
        assert conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 8"
        ).fetchone() is None
    finally:
        conn.close()

    assert _cli(root, "audit", "check").returncode == 7
    assert _cli(root, "validate", "--strict").returncode == 1
    assert _cli(root, "migrate").returncode == 0
    assert _cli(root, "audit", "check").returncode == 0
    assert _cli(root, "validate", "--strict").returncode == 0


@pytest.mark.parametrize(
    ("point", "orphan_kind"),
    [
        ("before_evidence_temp_write", None),
        ("after_evidence_temp_write_before_rename", "orphan_temp_evidence"),
        ("after_evidence_rename_before_commit", "orphan_evidence_manifest"),
    ],
)
def test_evidence_crash_points_are_clean_or_detectable(
    tmp_path: Path,
    point: str,
    orphan_kind: str | None,
) -> None:
    root = tmp_path / point
    _init(root)
    source = root / "artifact.txt"
    source.write_text("evidence bytes", encoding="utf-8")
    marker = tmp_path / f"{point}.marker.json"

    crashed = _cli(
        root,
        "evidence",
        "add",
        "--file",
        str(source),
        "--summary",
        point,
        env=_fault_env(point, marker),
    )
    assert crashed.returncode != 0
    assert marker.exists()
    checked = _cli(root, "audit", "check")
    report = _json(checked)
    if orphan_kind is None:
        assert checked.returncode == 0
    else:
        assert checked.returncode == 6
        types = {
            item["type"]
            for item in report["anomalies"]["human_review"]
        }
        assert orphan_kind in types
        preview = _cli(root, "audit", "repair", "--dry-run")
        assert preview.returncode == 6
        # The contract requires review instead of silent deletion. Quarantine the
        # unreferenced artifact outside the Evidence tree, then re-check.
        quarantine = root / "recovery-quarantine"
        quarantine.mkdir()
        for candidate in (root / ".project-loop" / "evidence").rglob("*"):
            if candidate.is_file() and candidate.name != source.name:
                candidate.replace(quarantine / candidate.name)
        assert _cli(root, "audit", "check").returncode == 0
    assert _cli(root, "validate", "--strict").returncode == 0


def _writer(root: str, round_index: int, writer_index: int, barrier, queue) -> None:
    try:
        barrier.wait(timeout=15)
        goal_id = create_goal(
            ProjectPaths(root=Path(root)),
            title=f"stress {round_index}:{writer_index}",
        )
        queue.put(("ok", goal_id))
    except BaseException as exc:  # pragma: no cover - surfaced by parent assertion
        queue.put(("error", repr(exc)))


def test_eight_process_writers_repeated_without_lost_or_duplicate_events(tmp_path: Path) -> None:
    paths = _init(tmp_path / "writers")
    context = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
    writer_count = 8
    rounds = 2
    started = time.perf_counter()
    for round_index in range(rounds):
        barrier = context.Barrier(writer_count + 1)
        queue = context.Queue()
        processes = [
            context.Process(target=_writer, args=(str(paths.root), round_index, index, barrier, queue))
            for index in range(writer_count)
        ]
        for process in processes:
            process.start()
        barrier.wait(timeout=15)
        results = [queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            assert process.exitcode == 0
        assert all(status == "ok" for status, _ in results), results

    conn = connect(paths.db_path)
    try:
        rows = conn.execute("SELECT id, sequence FROM events ORDER BY sequence").fetchall()
        stress_goals = int(
            conn.execute("SELECT COUNT(*) AS n FROM goals WHERE title LIKE 'stress %'").fetchone()["n"]
        )
        assert list(conn.execute("PRAGMA foreign_key_check")) == []
    finally:
        conn.close()
    jsonl = [json.loads(line) for line in paths.events_path.read_text().splitlines()]
    assert stress_goals == writer_count * rounds
    assert [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
    assert [item["sequence"] for item in jsonl] == list(range(1, len(jsonl) + 1))
    assert len({row["id"] for row in rows}) == len(rows) == len(jsonl)
    assert _cli(paths.root, "audit", "check").returncode == 0
    assert _cli(paths.root, "validate", "--strict").returncode == 0
    _write_ci_summary(
        "concurrent-writers",
        {
            "writers": writer_count,
            "rounds": rounds,
            "mutations": writer_count * rounds,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "event_count": len(rows),
        },
    )


def _locked_writer(root: str, ready, queue) -> None:
    ready.set()
    try:
        queue.put(("ok", create_goal(ProjectPaths(root=Path(root)), title="after migration lock")))
    except BaseException as exc:  # pragma: no cover - surfaced by parent assertion
        queue.put(("error", repr(exc)))


def test_migration_exclusive_lock_blocks_then_releases_writer(tmp_path: Path) -> None:
    paths = _init(tmp_path / "migration-lock")
    context = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
    ready = context.Event()
    queue = context.Queue()
    process = context.Process(target=_locked_writer, args=(str(paths.root), ready, queue))
    with AdvisoryLock(paths.loop_dir / "project.lock", exclusive=True):
        process.start()
        assert ready.wait(timeout=10)
        assert process.is_alive()
        assert queue.empty()
    status, detail = queue.get(timeout=20)
    process.join(timeout=20)
    assert (status, process.exitcode) == ("ok", 0), detail
    assert _cli(paths.root, "audit", "check").returncode == 0
    assert _cli(paths.root, "validate", "--strict").returncode == 0


def _projector_worker(root: str, barrier, queue) -> None:
    barrier.wait(timeout=15)
    queue.put(project_pending_events(ProjectPaths(root=Path(root))).to_dict())


def test_projector_and_mutation_started_together_preserve_order(tmp_path: Path) -> None:
    paths = _init(tmp_path / "projector-race")
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="pending_for_race",
            entity_type="test",
            entity_id="race",
            payload={},
        )
        conn.commit()
    finally:
        conn.close()
    context = multiprocessing.get_context("spawn" if os.name == "nt" else "fork")
    barrier = context.Barrier(3)
    queue = context.Queue()
    projector = context.Process(target=_projector_worker, args=(str(paths.root), barrier, queue))
    writer = context.Process(target=_writer, args=(str(paths.root), 99, 0, barrier, queue))
    projector.start()
    writer.start()
    barrier.wait(timeout=15)
    results = [queue.get(timeout=20), queue.get(timeout=20)]
    projector.join(timeout=20)
    writer.join(timeout=20)
    assert projector.exitcode == writer.exitcode == 0, results
    assert _cli(paths.root, "audit", "check").returncode == 0
    assert _cli(paths.root, "validate", "--strict").returncode == 0


def test_sqlite_busy_timeout_is_bounded_and_releases_operation_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _init(tmp_path / "busy")
    blocker = connect(paths.db_path)
    blocker.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(db_module, "SQLITE_BUSY_TIMEOUT_MS", 100)
    started = time.monotonic()
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            connect_mutation(paths)
    finally:
        blocker.rollback()
        blocker.close()
    assert time.monotonic() - started < 2
    conn = connect_mutation(paths)
    conn.rollback()


@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EACCES])
def test_projector_disk_and_permission_errors_remain_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
) -> None:
    paths = _init(tmp_path / f"io-{error_number}")
    conn = connect(paths.db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="io_fault",
            entity_type="test",
            entity_id=str(error_number),
            payload={},
        )
        conn.commit()
    finally:
        conn.close()
    original_fsync = outbox_module.os.fsync

    def fail_fsync(fd: int) -> None:
        raise OSError(error_number, os.strerror(error_number))

    monkeypatch.setattr(outbox_module.os, "fsync", fail_fsync)
    result = project_pending_events(paths)
    assert result.projection == "pending"
    report = audit_check(paths)
    assert report["counts"]["anomalies_by_classification"]["repairable"] >= 1
    monkeypatch.setattr(outbox_module.os, "fsync", original_fsync)
    monkeypatch.setattr(outbox_module, "_retry_is_due", lambda value: True)
    assert project_pending_events(paths).ok
    assert audit_check(paths)["ok"]


def test_evidence_permission_error_rolls_back_without_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _init(tmp_path / "evidence-permission")
    source = paths.root / "artifact.txt"
    source.write_text("bytes", encoding="utf-8")
    original_write_text = Path.write_text

    def deny_manifest(path: Path, *args, **kwargs):
        if path.name.endswith(".json.tmp"):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", deny_manifest)
    with pytest.raises(DataStoreError, match="Permission denied"):
        record_adhoc_evidence(paths, files=[str(source)], summary="permission")
    assert audit_check(paths)["ok"]
