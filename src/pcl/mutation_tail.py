from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .action_routing import next_action
from .db import connect
from .paths import ProjectPaths
from .project_config import dashboard_auto_render
from .renderer import render_dashboard


MUTATION_TAIL_CONTRACT_VERSION = "mutation-tail/v1"
RENDER_RECEIPT_CONTRACT_VERSION = "render-receipt/v1"


def apply_mutation_tail(
    paths: ProjectPaths,
    payload: dict[str, Any],
    *,
    target_id: str,
    changed: bool,
) -> dict[str, Any]:
    """Attach read-only routing and optional post-commit render to one result."""

    target = {
        "type": "task" if target_id.startswith("T-") else "goal",
        "id": target_id,
    }
    recovery = _read_only_recovery(target_id)
    tail: dict[str, Any] = {
        "contract_version": MUTATION_TAIL_CONTRACT_VERSION,
        "mutation_committed": changed,
        "safe_to_retry_original": not changed,
        "target": target,
        "next_action": None,
        "render": {
            "contract_version": RENDER_RECEIPT_CONTRACT_VERSION,
            "status": "not_changed" if not changed else "pending",
            "state_high_watermark": None,
            "artifact": None,
            "data_artifact": None,
            "error": None,
            "recovery": None,
        },
        "post_commit_status": "not_changed" if not changed else "complete",
        "errors": [],
    }

    try:
        tail["next_action"] = next_action(paths, target=target_id)
    except Exception as exc:
        _record_post_commit_failure(
            tail,
            phase="next_action",
            error=exc,
            recovery=recovery,
        )

    if not changed:
        return {**payload, "mutation_tail": tail}

    try:
        high_watermark = _state_high_watermark(paths)
        tail["render"]["state_high_watermark"] = high_watermark
        if not dashboard_auto_render(paths.root):
            tail["render"]["status"] = "disabled"
            return {**payload, "mutation_tail": tail}

        render_dashboard(paths)
        tail["render"].update(
            {
                "status": "rendered",
                "artifact": _artifact_receipt(paths.dashboard_html),
                "data_artifact": _artifact_receipt(paths.dashboard_data),
            }
        )
    except Exception as exc:
        tail["render"]["status"] = "failed"
        tail["render"]["error"] = str(exc)
        tail["render"]["recovery"] = recovery
        _record_post_commit_failure(
            tail,
            phase="render",
            error=exc,
            recovery=recovery,
        )
    return {**payload, "mutation_tail": tail}


def _state_high_watermark(paths: ProjectPaths) -> dict[str, Any]:
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            "SELECT id, sequence FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {"event_id": None, "sequence": 0}
        return {
            "event_id": str(row["id"]),
            "sequence": int(row["sequence"]),
        }
    finally:
        conn.close()


def _artifact_receipt(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _read_only_recovery(target_id: str) -> dict[str, Any]:
    return {
        "authority": "read_only",
        "command": f"pcl validate --target {target_id} --summary --json",
        "retry_original": False,
    }


def _record_post_commit_failure(
    tail: dict[str, Any],
    *,
    phase: str,
    error: Exception,
    recovery: dict[str, Any],
) -> None:
    tail["post_commit_status"] = "partial"
    tail["safe_to_retry_original"] = False
    tail["errors"].append({"phase": phase, "message": str(error)})
    tail["recovery"] = recovery
