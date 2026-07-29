from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .action_routing import next_action
from .db import connect_read_only
from .paths import ProjectPaths
from .project_config import dashboard_auto_render
from .renderer import render_dashboard


MUTATION_TAIL_CONTRACT_VERSION = "mutation-tail/v1"
RENDER_RECEIPT_CONTRACT_VERSION = "render-receipt/v1"
MAX_RENDER_ATTEMPTS = 2


class RenderStateChangedError(RuntimeError):
    def __init__(self, observations: list[dict[str, Any]]) -> None:
        super().__init__(
            "Project state changed during dashboard rendering after "
            f"{len(observations)} bounded attempts."
        )
        self.observations = observations


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
            "consistency": None,
            "error": None,
            "recovery": None,
        },
        "post_commit_status": "not_changed" if not changed else "complete",
        "errors": [],
    }

    auto_render: bool | None = None
    if changed:
        try:
            auto_render = dashboard_auto_render(paths.root)
        except Exception as exc:
            _record_render_failure(
                tail,
                phase="dashboard_config",
                code="config_dashboard_auto_render_invalid",
                error=exc,
                recovery=recovery,
            )
            return _result_with_tail(payload, tail)

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
        return _result_with_tail(payload, tail)

    if not auto_render:
        try:
            tail["render"]["state_high_watermark"] = _state_high_watermark(paths)
            tail["render"]["status"] = "disabled"
        except Exception as exc:
            _record_render_failure(
                tail,
                phase="render_receipt",
                code="render_receipt_unavailable",
                error=exc,
                recovery=recovery,
            )
        return _result_with_tail(payload, tail)

    try:
        render_result = _render_consistently(paths)
        tail["render"].update(
            {
                "status": "rendered",
                **render_result,
            }
        )
    except RenderStateChangedError as exc:
        tail["render"]["consistency"] = {
            "status": "unstable",
            "attempts": len(exc.observations),
            "observations": exc.observations,
        }
        if exc.observations:
            tail["render"]["state_high_watermark"] = exc.observations[-1]["after"]
        _record_render_failure(
            tail,
            phase="render_consistency",
            code="render_state_changed",
            error=exc,
            recovery=recovery,
        )
    except Exception as exc:
        _record_render_failure(
            tail,
            phase="render",
            code="render_failed",
            error=exc,
            recovery=recovery,
        )
    return _result_with_tail(payload, tail)


def _state_high_watermark(paths: ProjectPaths) -> dict[str, Any]:
    conn = connect_read_only(paths.db_path)
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


def _render_consistently(paths: ProjectPaths) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for attempt in range(1, MAX_RENDER_ATTEMPTS + 1):
        before = _state_high_watermark(paths)
        render_dashboard(paths)
        after = _state_high_watermark(paths)
        observations.append(
            {
                "attempt": attempt,
                "before": before,
                "after": after,
            }
        )
        if before == after:
            return {
                "state_high_watermark": after,
                "artifact": _artifact_receipt(paths.dashboard_html),
                "data_artifact": _artifact_receipt(paths.dashboard_data),
                "consistency": {
                    "status": "stable",
                    "attempts": attempt,
                    "before": before,
                    "after": after,
                },
            }
    raise RenderStateChangedError(observations)


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
    code: str = "post_commit_failed",
    error: Exception,
    recovery: dict[str, Any],
) -> None:
    tail["post_commit_status"] = "partial"
    tail["safe_to_retry_original"] = False
    tail["errors"].append(
        {
            "phase": phase,
            "code": code,
            "message": str(error),
        }
    )
    tail["recovery"] = recovery


def _record_render_failure(
    tail: dict[str, Any],
    *,
    phase: str,
    code: str,
    error: Exception,
    recovery: dict[str, Any],
) -> None:
    tail["render"]["status"] = "failed"
    tail["render"]["error"] = str(error)
    tail["render"]["recovery"] = recovery
    _record_post_commit_failure(
        tail,
        phase=phase,
        code=code,
        error=error,
        recovery=recovery,
    )


def _result_with_tail(
    payload: dict[str, Any],
    tail: dict[str, Any],
) -> dict[str, Any]:
    result = {**payload, "mutation_tail": tail}
    if tail["post_commit_status"] != "partial":
        return result
    result.update(
        {
            "mutation_committed": tail["mutation_committed"],
            "safe_to_retry_original": tail["safe_to_retry_original"],
            "post_commit_status": "partial",
            "post_commit_diagnostics": list(tail["errors"]),
            "recovery": tail["recovery"],
        }
    )
    return result
