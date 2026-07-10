from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .timeutil import utc_now_iso


def append_event(
    *,
    conn: sqlite3.Connection,
    events_path: Path,
    event_type: str,
    entity_type: str,
    entity_id: str | None,
    payload: dict[str, Any],
) -> str:
    event_id = f"EV-{uuid.uuid4().hex[:12].upper()}"
    created_at = utc_now_iso()
    del events_path  # retained in the public signature for caller compatibility
    sequence = int(conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM events").fetchone()[0])
    conn.execute(
        """
        INSERT INTO events(id, sequence, event_type, entity_type, entity_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            sequence,
            event_type,
            entity_type,
            entity_id,
            json.dumps(payload, ensure_ascii=False),
            created_at,
        ),
    )
    outbox_id = f"OB-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        """
        INSERT INTO outbox_records(
          id, event_id, sink, idempotency_key, status, attempts,
          next_attempt_at, last_error, created_at, updated_at, delivered_at
        )
        VALUES (?, ?, 'jsonl', ?, 'pending', 0, NULL, NULL, ?, ?, NULL)
        """,
        (outbox_id, event_id, f"jsonl:{event_id}", created_at, created_at),
    )
    return event_id
