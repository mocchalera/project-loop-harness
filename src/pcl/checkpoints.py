from __future__ import annotations

import json
import subprocess
from typing import Any

from .db import connect, connect_mutation
from .evidence import record_inline_evidence
from .events import append_event
from .errors import InvalidInputError
from .guards import require_initialized
from .paths import ProjectPaths
from .project_config import checkpoint_configuration


CHECKPOINT_REVIEW_TYPES = {"integration", "commit", "ux", "release", "package"}


def checkpoint_status(paths: ProjectPaths) -> dict[str, Any]:
    configuration = checkpoint_configuration(paths.root)
    require_initialized(paths)

    conn = connect(paths.db_path)
    try:
        latest = conn.execute(
            """
            SELECT id, payload_json, created_at, rowid
            FROM events
            WHERE event_type = 'checkpoint_recorded'
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
        latest_rowid = int(latest["rowid"]) if latest is not None else 0
        feature_events_since_checkpoint = conn.execute(
            """
            SELECT entity_id, payload_json
            FROM events
            WHERE event_type = 'feature_status_updated'
              AND entity_type = 'feature'
              AND rowid > ?
              AND entity_id IS NOT NULL
            ORDER BY rowid
            """,
            (latest_rowid,),
        ).fetchall()
        status_counts = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM features
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        }
        passed_runs_since = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM events
                WHERE event_type = 'workflow_run_completed'
                  AND rowid > ?
                """,
                (latest_rowid,),
            ).fetchone()["count"]
        )
        open_goal_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM goals
                WHERE status NOT IN ('closed', 'cancelled')
                """
            ).fetchone()["count"]
        )
        done_feature_ids = _done_feature_ids(feature_events_since_checkpoint)
        git_state = _git_status(paths)
        threshold = int(configuration["feature_interval"])
        threshold_reached = len(done_feature_ids) >= threshold
        recommended = threshold_reached and configuration["mode"] != "off"
        return {
            "ok": True,
            "checkpoint_recommended": recommended,
            "checkpoint_requires_human": recommended and configuration["mode"] == "blocking",
            "mode": configuration["mode"],
            "threshold": threshold,
            "threshold_reached": threshold_reached,
            "completed_features_since_checkpoint": len(done_feature_ids),
            "completed_feature_ids_since_checkpoint": done_feature_ids,
            "passed_workflow_runs_since_checkpoint": passed_runs_since,
            "feature_status_counts": status_counts,
            "open_goal_count": open_goal_count,
            "latest_checkpoint": None if latest is None else dict(latest),
            "git": git_state,
        }
    finally:
        conn.close()


def record_checkpoint(
    paths: ProjectPaths,
    *,
    summary: str,
    evidence: str,
    review_type: str = "integration",
) -> dict[str, Any]:
    require_initialized(paths)
    summary = summary.strip()
    evidence = evidence.strip()
    review_type = review_type.strip()
    if not summary:
        raise InvalidInputError("--summary is required to record a checkpoint.", details={"field": "summary"})
    if not evidence:
        raise InvalidInputError("--evidence is required to record a checkpoint.", details={"field": "evidence"})
    if review_type not in CHECKPOINT_REVIEW_TYPES:
        raise InvalidInputError(
            f"Invalid checkpoint review type: {review_type}",
            details={"review_type": review_type, "allowed": sorted(CHECKPOINT_REVIEW_TYPES)},
        )

    before = checkpoint_status(paths)
    conn = connect_mutation(paths)
    try:
        evidence_id = record_inline_evidence(
            conn,
            evidence_type="checkpoint_review",
            summary=evidence,
            context=f"checkpoint/{review_type}",
            command="pcl checkpoint record",
        )
        payload = {
            "summary": summary,
            "evidence": evidence,
            "evidence_id": evidence_id,
            "review_type": review_type,
            "status_before": {
                "threshold": before["threshold"],
                "completed_features_since_checkpoint": before["completed_features_since_checkpoint"],
                "completed_feature_ids_since_checkpoint": before["completed_feature_ids_since_checkpoint"],
                "passed_workflow_runs_since_checkpoint": before["passed_workflow_runs_since_checkpoint"],
                "feature_status_counts": before["feature_status_counts"],
                "open_goal_count": before["open_goal_count"],
                "git": before["git"],
            },
        }
        event_id = append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="checkpoint_recorded",
            entity_type="checkpoint",
            entity_id=evidence_id,
            payload=payload,
        )
        conn.commit()
        after = checkpoint_status(paths)
        return {
            "ok": True,
            "checkpoint_id": evidence_id,
            "event_id": event_id,
            "evidence_id": evidence_id,
            "review_type": review_type,
            "summary": summary,
            "status_before": payload["status_before"],
            "status_after": {
                "checkpoint_recommended": after["checkpoint_recommended"],
                "completed_features_since_checkpoint": after["completed_features_since_checkpoint"],
            },
        }
    finally:
        conn.close()


def _git_status(paths: ProjectPaths) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=paths.root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "dirty_worktree": False, "dirty_file_count": 0, "porcelain": []}
    if result.returncode != 0:
        return {"available": False, "dirty_worktree": False, "dirty_file_count": 0, "porcelain": []}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return {
        "available": True,
        "dirty_worktree": bool(lines),
        "dirty_file_count": len(lines),
        "porcelain": lines[:50],
    }


def _done_feature_ids(rows) -> list[str]:
    done: dict[str, None] = {}
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("status") == "done":
            done[str(row["entity_id"])] = None
    return sorted(done)
