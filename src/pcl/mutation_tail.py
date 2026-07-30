from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .action_routing import next_action
from .db import connect_read_only
from .locks import project_operation_lock
from .paths import ProjectPaths
from .project_config import dashboard_auto_render
from .renderer import render_dashboard
from .validation_projection import project_validation_result
from .validators import validate_project


MUTATION_TAIL_CONTRACT_VERSION = "mutation-tail/v1"
RENDER_RECEIPT_CONTRACT_VERSION = "render-receipt/v1"
MAX_RENDER_ATTEMPTS = 2
DIRECT_TAIL_VALIDATION_CONTRACT_VERSION = "mutation-tail-validation/v1"
DIRECT_TAIL_CONSISTENCY_CONTRACT_VERSION = "event-hwm-consistency/v1"


class RenderStateChangedError(RuntimeError):
    def __init__(self, observations: list[dict[str, Any]]) -> None:
        super().__init__(
            "Project state changed during dashboard rendering after "
            f"{len(observations)} bounded attempts."
        )
        self.observations = observations


def apply_direct_setup_tail(
    paths: ProjectPaths,
    payload: dict[str, Any],
    *,
    target_id: str,
    changed: bool,
) -> dict[str, Any]:
    """Run the bounded Direct Setup validation/routing/locked-render tail."""

    target = {"type": "task", "id": target_id}
    recovery = _read_only_recovery(target_id)
    tail: dict[str, Any] = {
        "contract_version": MUTATION_TAIL_CONTRACT_VERSION,
        "mutation_committed": changed,
        "safe_to_retry_original": True,
        "retry_recommended": False,
        "target": target,
        "validation": None,
        "next_action": None,
        "render": _direct_render_receipt("not_changed" if not changed else "pending"),
        "consistency": None,
        "post_commit_status": "not_changed" if not changed else "complete",
        "errors": [],
        "recovery": None,
    }
    observations: list[dict[str, Any]] = []
    for attempt in range(1, MAX_RENDER_ATTEMPTS + 1):
        before = _state_high_watermark(paths)
        validation_result = validate_project(paths)
        validation_projection = project_validation_result(
            paths,
            validation_result,
            target_id=target_id,
            active_only=False,
            summary=True,
        )
        after_validation = _state_high_watermark(paths)
        observation: dict[str, Any] = {
            "attempt": attempt,
            "before": before,
            "after_validation": after_validation,
        }
        observations.append(observation)
        if before != after_validation:
            if attempt < MAX_RENDER_ATTEMPTS:
                continue
            return _direct_unstable_result(
                payload,
                tail,
                observations=observations,
                recovery=recovery,
                last_hwm=after_validation,
                phase="validation_consistency",
            )
        validation = _direct_validation_receipt(
            validation_projection,
            status="passed" if validation_result.ok else "failed",
            before=before,
            after=after_validation,
            attempts=attempt,
        )
        if not validation_result.ok:
            tail["validation"] = validation
            tail["next_action"] = None
            tail["render"] = {
                **_direct_render_receipt("skipped_validation_failed"),
                "state_high_watermark": after_validation,
                "recovery": recovery,
            }
            tail["consistency"] = _direct_consistency(
                status="stable",
                attempts=attempt,
                before=before,
                after=after_validation,
                observations=observations,
            )
            tail["post_commit_status"] = "partial"
            tail["errors"] = [
                {
                    "phase": "validation",
                    "code": "post_commit_validation_failed",
                    "message": "Full project validation failed.",
                }
            ]
            tail["recovery"] = recovery
            return _result_with_tail(payload, tail)

        try:
            routed = next_action(paths, target=target_id)
        except Exception as exc:
            after_routing = _state_high_watermark(paths)
            observation["after_routing"] = after_routing
            if before != after_routing:
                if attempt < MAX_RENDER_ATTEMPTS:
                    continue
                return _direct_unstable_result(
                    payload,
                    tail,
                    observations=observations,
                    recovery=recovery,
                    last_hwm=after_routing,
                    phase="routing_consistency",
                )
            tail["validation"] = validation
            tail["next_action"] = None
            tail["render"] = {
                **_direct_render_receipt("skipped_routing_failed"),
                "state_high_watermark": after_routing,
                "recovery": recovery,
            }
            tail["consistency"] = _direct_consistency(
                status="stable",
                attempts=attempt,
                before=before,
                after=after_routing,
                observations=observations,
            )
            tail["errors"] = [
                {
                    "phase": "next_action",
                    "code": "post_commit_failed",
                    "message": str(exc),
                }
            ]
            tail["post_commit_status"] = "partial"
            tail["recovery"] = recovery
            return _result_with_tail(payload, tail)
        after_routing = _state_high_watermark(paths)
        observation["after_routing"] = after_routing
        if before != after_routing:
            if attempt < MAX_RENDER_ATTEMPTS:
                continue
            return _direct_unstable_result(
                payload,
                tail,
                observations=observations,
                recovery=recovery,
                last_hwm=after_routing,
                phase="routing_consistency",
            )

        tail["validation"] = validation
        tail["next_action"] = routed
        if not changed:
            tail["render"] = {
                **_direct_render_receipt("not_changed"),
                "state_high_watermark": after_routing,
            }
            tail["consistency"] = _direct_consistency(
                status="stable",
                attempts=attempt,
                before=before,
                after=after_routing,
                observations=observations,
            )
            tail["post_commit_status"] = "not_changed"
            return _result_with_tail(payload, tail)

        try:
            auto_render = dashboard_auto_render(paths.root)
        except Exception as exc:
            tail["render"] = {
                **_direct_render_receipt("failed"),
                "state_high_watermark": after_routing,
                "error": str(exc),
                "recovery": recovery,
            }
            tail["post_commit_status"] = "partial"
            tail["errors"] = [
                {
                    "phase": "dashboard_config",
                    "code": "config_dashboard_auto_render_invalid",
                    "message": str(exc),
                }
            ]
            tail["recovery"] = recovery
            return _result_with_tail(payload, tail)
        if not auto_render:
            tail["render"] = {
                **_direct_render_receipt("disabled"),
                "state_high_watermark": after_routing,
            }
            tail["consistency"] = _direct_consistency(
                status="stable",
                attempts=attempt,
                before=before,
                after=after_routing,
                observations=observations,
            )
            return _result_with_tail(payload, tail)

        with project_operation_lock(paths.loop_dir, exclusive=True):
            lock_before = _state_high_watermark(paths)
            observation["lock_before"] = lock_before
            if lock_before != before:
                if attempt < MAX_RENDER_ATTEMPTS:
                    continue
                return _direct_unstable_result(
                    payload,
                    tail,
                    observations=observations,
                    recovery=recovery,
                    last_hwm=lock_before,
                    phase="render_lock_consistency",
                )
            try:
                render_dashboard(paths)
                artifact = _artifact_receipt(paths.dashboard_html)
                data_artifact = _artifact_receipt(paths.dashboard_data)
                lock_after = _state_high_watermark(paths)
                observation["lock_after"] = lock_after
                if lock_after != before:
                    return _direct_unstable_after_render_result(
                        payload,
                        tail,
                        observations=observations,
                        recovery=recovery,
                        last_hwm=lock_after,
                    )
            except Exception as exc:
                tail["render"] = {
                    **_direct_render_receipt("failed"),
                    "state_high_watermark": lock_before,
                    "error": str(exc),
                    "recovery": recovery,
                }
                tail["post_commit_status"] = "partial"
                tail["errors"] = [
                    {
                        "phase": "render",
                        "code": "render_failed",
                        "message": str(exc),
                    }
                ]
                tail["recovery"] = recovery
                return _result_with_tail(payload, tail)
        tail["render"] = {
            **_direct_render_receipt("rendered"),
            "state_high_watermark": lock_after,
            "artifact": artifact,
            "data_artifact": data_artifact,
            "consistency": {
                "status": "stable",
                "attempts": attempt,
                "before": before,
                "after": lock_after,
                "lock_before": lock_before,
                "lock_after": lock_after,
                "lock": "project_operation:exclusive",
            },
        }
        tail["consistency"] = _direct_consistency(
            status="stable",
            attempts=attempt,
            before=before,
            after=lock_after,
            observations=observations,
        )
        return _result_with_tail(payload, tail)
    raise AssertionError("Direct Setup tail exceeded its bounded attempts.")


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
    recovery = _read_only_recovery(
        target_id,
        retry_original=not changed,
    )
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
        artifact = _artifact_receipt(paths.dashboard_html)
        data_artifact = _artifact_receipt(paths.dashboard_data)
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
                "artifact": artifact,
                "data_artifact": data_artifact,
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


def _read_only_recovery(
    target_id: str,
    *,
    retry_original: bool = False,
) -> dict[str, Any]:
    return {
        "authority": "read_only",
        "command": f"pcl validate --target {target_id} --summary --json",
        "retry_original": retry_original,
    }


def _direct_render_receipt(status: str) -> dict[str, Any]:
    return {
        "contract_version": RENDER_RECEIPT_CONTRACT_VERSION,
        "status": status,
        "state_high_watermark": None,
        "artifact": None,
        "data_artifact": None,
        "consistency": None,
        "error": None,
        "recovery": None,
    }


def _direct_validation_receipt(
    projection: dict[str, Any],
    *,
    status: str,
    before: dict[str, Any],
    after: dict[str, Any],
    attempts: int,
) -> dict[str, Any]:
    return {
        "contract_version": DIRECT_TAIL_VALIDATION_CONTRACT_VERSION,
        "status": status,
        "ok": bool(projection.get("ok")),
        "state_high_watermark": after,
        "full_validation": projection.get("full_validation"),
        "validation_projection": projection.get("validation_projection"),
        "consistency": {
            "status": "stable",
            "attempts": attempts,
            "before": before,
            "after": after,
        },
    }


def _direct_consistency(
    *,
    status: str,
    attempts: int,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contract_version": DIRECT_TAIL_CONSISTENCY_CONTRACT_VERSION,
        "status": status,
        "attempts": attempts,
        "before": before,
        "after": after,
        "observations": list(observations),
    }


def _direct_unstable_result(
    payload: dict[str, Any],
    tail: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    recovery: dict[str, Any],
    last_hwm: dict[str, Any],
    phase: str,
) -> dict[str, Any]:
    tail["validation"] = {
        "contract_version": DIRECT_TAIL_VALIDATION_CONTRACT_VERSION,
        "status": "unstable",
        "ok": None,
        "state_high_watermark": last_hwm,
        "full_validation": None,
        "validation_projection": None,
        "consistency": _direct_consistency(
            status="unstable",
            attempts=len(observations),
            before=observations[0]["before"] if observations else None,
            after=last_hwm,
            observations=observations,
        ),
    }
    tail["next_action"] = None
    tail["render"] = {
        **_direct_render_receipt("skipped_state_changed"),
        "state_high_watermark": last_hwm,
        "recovery": recovery,
    }
    tail["consistency"] = _direct_consistency(
        status="unstable",
        attempts=len(observations),
        before=observations[0]["before"] if observations else None,
        after=last_hwm,
        observations=observations,
    )
    tail["post_commit_status"] = "partial"
    tail["errors"] = [
        {
            "phase": phase,
            "code": "post_commit_state_changed",
            "message": "Project state changed during the bounded Direct Setup tail.",
        }
    ]
    tail["recovery"] = recovery
    return _result_with_tail(payload, tail)


def _direct_unstable_after_render_result(
    payload: dict[str, Any],
    tail: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    recovery: dict[str, Any],
    last_hwm: dict[str, Any],
) -> dict[str, Any]:
    tail["next_action"] = None
    tail["render"] = {
        **_direct_render_receipt("failed"),
        "state_high_watermark": last_hwm,
        "error": "Project state changed while the exclusive render lock was held.",
        "recovery": recovery,
    }
    tail["consistency"] = _direct_consistency(
        status="unstable",
        attempts=len(observations),
        before=observations[0]["before"] if observations else None,
        after=last_hwm,
        observations=observations,
    )
    tail["post_commit_status"] = "partial"
    tail["errors"] = [
        {
            "phase": "render_consistency",
            "code": "render_state_changed",
            "message": "Project state changed while the exclusive render lock was held.",
        }
    ]
    tail["recovery"] = recovery
    return _result_with_tail(payload, tail)


def _record_post_commit_failure(
    tail: dict[str, Any],
    *,
    phase: str,
    code: str = "post_commit_failed",
    error: Exception,
    recovery: dict[str, Any],
) -> None:
    tail["post_commit_status"] = "partial"
    tail["safe_to_retry_original"] = not bool(tail["mutation_committed"])
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


def mutation_tail_warning(result: dict[str, Any]) -> str | None:
    """Format an honest warning for a partial post-commit tail."""

    tail = result.get("mutation_tail")
    if not isinstance(tail, dict) or tail.get("post_commit_status") != "partial":
        return None
    committed = bool(tail.get("mutation_committed"))
    safe = bool(tail.get("safe_to_retry_original"))
    recovery = tail.get("recovery")
    command = recovery.get("command") if isinstance(recovery, dict) else None
    diagnostics = tail.get("errors")
    codes = ", ".join(
        str(item.get("code"))
        for item in diagnostics
        if isinstance(item, dict) and item.get("code")
    )
    if committed and safe:
        consequence = (
            "Mutation committed; the original retry is idempotent but is not the "
            "recommended recovery."
        )
    elif committed:
        consequence = (
            "Mutation committed, but post-commit processing was partial. "
            "Do not retry the original mutation."
        )
    elif safe:
        consequence = (
            "No authoritative mutation was committed by this invocation; "
            "retry remains idempotent."
        )
    else:
        consequence = (
            "No authoritative mutation was reported, but automatic retry safety "
            "could not be established."
        )
    return (
        "WARNING: post_commit_status=partial "
        f"mutation_committed={str(committed).lower()} "
        f"safe_to_retry_original={str(safe).lower()}"
        + (f" diagnostics={codes}" if codes else "")
        + f". {consequence}"
        + (f" Inspect with: {command}" if command else "")
    )
