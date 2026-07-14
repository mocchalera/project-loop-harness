from __future__ import annotations

from typing import Any, Iterable, Mapping


MAX_FINISH_TIMEOUT_SECONDS = 600


def finish_timeout_recovery(
    *,
    target: Mapping[str, Any],
    checks: Iterable[Mapping[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any] | None:
    timed_out = next((check for check in checks if check.get("status") == "timed_out"), None)
    if timed_out is None:
        return None

    evidence_id = str(timed_out["evidence_id"])
    if timeout_seconds < MAX_FINISH_TIMEOUT_SECONDS:
        retry_command = (
            f"pcl finish --emit-packet --{target['type']} {target['id']} "
            f"--timeout {MAX_FINISH_TIMEOUT_SECONDS} --json"
        )
        return {
            "available": True,
            "reason": "finish_check_timed_out",
            "timed_out_evidence_id": evidence_id,
            "previous_timeout_seconds": timeout_seconds,
            "suggested_timeout_seconds": MAX_FINISH_TIMEOUT_SECONDS,
            "retry_command": retry_command,
            "diagnostic_command": f"pcl evidence show {evidence_id} --json",
        }

    return {
        "available": False,
        "reason": "finish_timeout_limit_reached",
        "timed_out_evidence_id": evidence_id,
        "previous_timeout_seconds": timeout_seconds,
        "suggested_timeout_seconds": None,
        "retry_command": None,
        "diagnostic_command": f"pcl evidence show {evidence_id} --json",
    }


def completion_packet_timeout_action(packet: Mapping[str, Any]) -> dict[str, Any] | None:
    if packet.get("outcome") != "INCOMPLETE_VALIDATION":
        return None
    checks = packet.get("checks")
    if not isinstance(checks, list):
        return None
    timed_out = next(
        (
            check
            for check in checks
            if isinstance(check, dict) and check.get("status") == "timed_out"
        ),
        None,
    )
    if timed_out is None:
        return None
    next_action = packet.get("next_action")
    if not isinstance(next_action, dict):
        return None
    command = next_action.get("command")
    if not isinstance(command, str) or not command:
        return None
    target = packet.get("target")
    if not isinstance(target, dict):
        return None
    retry_command = (
        f"pcl finish --emit-packet --{target.get('type')} {target.get('id')} "
        f"--timeout {MAX_FINISH_TIMEOUT_SECONDS} --json"
    )
    artifact_ref = timed_out.get("artifact_ref")
    diagnostic_command = (
        f"pcl evidence show {str(artifact_ref).removeprefix('evidence:')} --json"
        if isinstance(artifact_ref, str) and artifact_ref.startswith("evidence:E-")
        else None
    )
    if command == retry_command:
        action_type = "retry_finish_timeout"
    elif diagnostic_command is not None and command == diagnostic_command:
        action_type = "diagnose_finish_timeout"
    else:
        return None
    return {
        "type": action_type,
        "command": command,
        "reason": str(next_action.get("text") or "A finish check timed out."),
    }
