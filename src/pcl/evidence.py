from __future__ import annotations

import sqlite3

from .ids import next_prefixed_id
from .timeutil import utc_now_iso


def record_inline_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_type: str,
    summary: str,
    context: str,
    command: str | None = None,
) -> str:
    evidence_id = next_prefixed_id(conn, "evidence", "E")
    conn.execute(
        """
        INSERT INTO evidence(id, type, path, command, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (evidence_id, evidence_type, f"inline:{context}", command, summary, utc_now_iso()),
    )
    return evidence_id
