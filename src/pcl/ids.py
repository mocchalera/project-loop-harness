from __future__ import annotations

import sqlite3

from .prefixed_ids import next_prefixed_id_strict


def next_prefixed_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    return next_prefixed_id_strict(conn, table=table, prefix=prefix)
