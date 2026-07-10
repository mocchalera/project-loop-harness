from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 8
SQLITE_BUSY_TIMEOUT_MS = 30_000


class MutationConnection(sqlite3.Connection):
    _operation_lock: Any = None
    _paths: Any = None
    projection_result: Any = None
    _authoritative_commit_completed = False

    def commit(self) -> None:
        from .test_faults import crash_if_requested

        crash_if_requested("before_sqlite_commit")
        super().commit()
        crash_if_requested("after_sqlite_commit_before_projector")
        if self._paths is None or self._authoritative_commit_completed:
            return
        self._authoritative_commit_completed = True
        try:
            from .outbox import pending_projection_result, project_pending_events

            try:
                self.projection_result = project_pending_events(
                    self._paths,
                    operation_lock_held=True,
                )
            except Exception as exc:
                self.projection_result = pending_projection_result(
                    self._paths,
                    error=str(exc),
                )
            if not self.projection_result.ok:
                from .errors import ProjectionPendingError

                raise ProjectionPendingError(details=self.projection_result.to_dict())
        finally:
            self._release_operation_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_operation_lock()

    def close(self) -> None:
        try:
            if self.in_transaction and not self._authoritative_commit_completed:
                super().rollback()
        finally:
            try:
                super().close()
            finally:
                self._release_operation_lock()

    def _release_operation_lock(self) -> None:
        if self._operation_lock is not None:
            self._operation_lock.release()
            self._operation_lock = None


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def connect_mutation(paths: Any) -> MutationConnection:
    from .locks import AdvisoryLock

    lock = AdvisoryLock(paths.loop_dir / "project.lock", exclusive=False)
    lock.acquire()
    try:
        conn = sqlite3.connect(
            paths.db_path,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            factory=MutationConnection,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn._operation_lock = lock
        conn._paths = paths
        conn.execute("BEGIN IMMEDIATE")
        return conn
    except BaseException:
        lock.release()
        raise


def initialize_database(db_path: Path, events_path: Path | None = None) -> object:
    from .migrations import apply_migrations
    from .paths import ProjectPaths

    loop_dir = db_path.parent
    loop_dir.mkdir(parents=True, exist_ok=True)
    if not db_path.exists():
        db_path.touch()
    paths = ProjectPaths(root=loop_dir.parent)
    if events_path is not None and events_path != paths.events_path:
        paths = ProjectPaths(root=events_path.parent.parent)
    return apply_migrations(paths)


def get_metadata(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def count_rows(conn: sqlite3.Connection, table_name: str, where: str = "", params: tuple = ()) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table_name}"
    if where:
        sql += f" WHERE {where}"
    row = conn.execute(sql, params).fetchone()
    return int(row["n"])
