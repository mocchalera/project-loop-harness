from __future__ import annotations

import sqlite3
from typing import Any

from .db import connect_mutation
from .errors import DataStoreError
from .events import append_event
from .guards import require_initialized
from .paths import ProjectPaths


CONTEXT_PACK_GENERATED_EVENT = "context_pack_generated"


def record_context_pack_usage(paths: ProjectPaths, pack: dict[str, Any]) -> dict[str, Any]:
    """Record one explicitly requested context-pack usage event."""
    require_initialized(paths)
    target = pack["target"]
    code_context = pack.get("code_context")
    relevance = code_context.get("relevance") if isinstance(code_context, dict) else None
    bound_receipt = isinstance(relevance, dict) and relevance.get("scope") == "target_bound"
    payload = {
        "estimated_token_count": int(pack["estimated_token_count"]),
        "token_estimator": str(pack["token_estimator"]),
        "target": {
            "type": str(target["type"]),
            "id": str(target["id"]),
        },
        "bound_receipt": bound_receipt,
        "truncated": bool(pack["truncated"]),
    }

    conn = connect_mutation(paths)
    try:
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=CONTEXT_PACK_GENERATED_EVENT,
            entity_type="context_pack",
            entity_id=str(target["id"]),
            payload=payload,
        )
        conn.commit()
        return {"ok": True, "event_id": event_id, "payload": payload}
    except sqlite3.Error as exc:
        conn.rollback()
        raise DataStoreError(f"Could not record context pack usage: {exc}") from exc
    finally:
        conn.close()
