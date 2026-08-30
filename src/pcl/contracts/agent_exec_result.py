from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "agent-exec-result/v1"
STATUSES = frozenset({"PASS", "FAIL", "TIMEOUT", "INFRA_ERROR", "INTERRUPTED", "FLAKY"})


def validate_agent_exec_result(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["$: expected object"]
    required = {
        "schema",
        "ok",
        "run_id",
        "created_at",
        "status",
        "exit_code",
        "shell_exit_code",
        "signal",
        "duration_ms",
        "command",
        "raw",
        "capture",
        "diagnostics",
        "termination",
        "retry_count",
        "exposed",
    }
    missing = sorted(required - set(payload))
    if missing:
        errors.append(f"$: missing required fields: {', '.join(missing)}")
    if payload.get("schema") != CONTRACT_VERSION:
        errors.append(f"$.schema: expected {CONTRACT_VERSION!r}")
    status = payload.get("status")
    if status not in STATUSES:
        errors.append("$.status: unknown status")
    if payload.get("ok") is not (status == "PASS"):
        errors.append("$.ok: must be true only for PASS")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.startswith("AX-"):
        errors.append("$.run_id: expected AX-prefixed string")
    for field in ("shell_exit_code", "duration_ms", "retry_count"):
        if not isinstance(payload.get(field), int) or payload[field] < 0:
            errors.append(f"$.{field}: expected non-negative integer")
    if not isinstance(payload.get("raw"), dict):
        errors.append("$.raw: expected object")
    if not isinstance(payload.get("diagnostics"), dict):
        errors.append("$.diagnostics: expected object")
    if status == "PASS" and payload.get("diagnostics", {}).get("preview"):
        errors.append("$.diagnostics.preview: PASS must not expose command output")
    return errors
