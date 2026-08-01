from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


SCHEMA_VERSION = 8
SQLITE_BUSY_TIMEOUT_MS = 30_000


class MutationConnection(sqlite3.Connection):
    _operation_lock: Any = None
    _paths: Any = None
    _precommit_guard: Any = None
    _postcommit_guard: Any = None
    _postcommit_authority_publisher: Any = None
    postcommit_authority_result: Any = None
    projection_result: Any = None
    _authoritative_commit_completed = False

    def commit(self) -> None:
        from .test_faults import crash_if_requested

        crash_if_requested("before_sqlite_commit")
        if self._precommit_guard is not None:
            self._precommit_guard()
        super().commit()
        if self._paths is None or self._authoritative_commit_completed:
            return
        self._authoritative_commit_completed = True
        try:
            # Task Accept uses this first post-commit callback only to classify
            # corruption after its retained-descriptor linearization point. It
            # runs before accepted authority, projection, render, or tail work.
            if self._postcommit_guard is not None:
                self._postcommit_guard()
            if self._postcommit_authority_publisher is not None:
                self.postcommit_authority_result = self._postcommit_authority_publisher()
            crash_if_requested("after_sqlite_commit_before_projector")
            from .outbox import pending_projection_result, project_pending_events

            try:
                self.projection_result = project_pending_events(
                    self._paths,
                    operation_lock_held=True,
                )
            except Exception as exc:
                try:
                    self.projection_result = pending_projection_result(
                        self._paths,
                        error=str(exc),
                    )
                except Exception as diagnostic_exc:
                    from .errors import ProjectionPendingError

                    raise ProjectionPendingError(
                        details={
                            "committed": True,
                            "projection": "unknown",
                            "delivered": 0,
                            "pending_count": None,
                            "first_pending_sequence": None,
                            "event_id": None,
                            "event_sequence": None,
                            "safe_next_action": (
                                "Run `pcl audit flush --json`; do not retry the "
                                "committed mutation."
                            ),
                            "error": str(exc),
                            "diagnostic_error": str(diagnostic_exc),
                            "mutation_committed": True,
                            "safe_to_retry_original": False,
                        }
                    ) from exc
            if not self.projection_result.ok:
                from .errors import ProjectionPendingError

                raise ProjectionPendingError(
                    details={
                        **self.projection_result.to_dict(),
                        "mutation_committed": True,
                        "safe_to_retry_original": False,
                    }
                )
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


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    absolute_path = db_path if db_path.is_absolute() else Path.cwd() / db_path
    uri = f"file:{quote(str(absolute_path), safe='/')}?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA query_only = ON")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def connect_mutation(
    paths: Any,
    *,
    exclusive: bool = False,
    operation_capability: object | None = None,
) -> MutationConnection:
    from .locks import AdvisoryLock
    from .locks import require_live_exclusive_project_operation_capability

    lock = None
    if operation_capability is None:
        lock = AdvisoryLock(paths.loop_dir / "project.lock", exclusive=exclusive)
        lock.acquire()
    else:
        if not exclusive:
            raise ValueError("A borrowed operation capability requires exclusive=True.")
        require_live_exclusive_project_operation_capability(
            operation_capability,
            loop_dir=paths.loop_dir,
        )
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
        if lock is not None:
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
