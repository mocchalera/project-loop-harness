from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 5


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
