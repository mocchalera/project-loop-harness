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
    record = {
        "id": event_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
        "created_at": created_at,
    }
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    conn.execute(
        """
        INSERT INTO events(id, event_type, entity_type, entity_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_id, event_type, entity_type, entity_id, json.dumps(payload, ensure_ascii=False), created_at),
    )
    return event_id
