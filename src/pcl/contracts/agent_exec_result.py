from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


AGENT_EXEC_RESULT_CONTRACT_VERSION = "agent-exec-result/v1"
AGENT_EXEC_STATUSES = frozenset(
    {"PASS", "FAIL", "TIMEOUT", "INFRA_ERROR", "INTERRUPTED", "FLAKY"}
)
AGENT_EXEC_DIAGNOSTIC_STRATEGIES = frozenset(
    {"none", "error-block", "stderr-tail", "combined-tail", "binary-omitted"}
)


@dataclass(frozen=True)
class AgentExecResultValidationResult:
    ok: bool
    errors: tuple[str, ...]


def agent_exec_result_schema() -> dict[str, Any]:
    path = Path(__file__).with_name("schemas") / "agent-exec-result-v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_agent_exec_result(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("agent execution result must be a JSON object")
    return payload


def validate_agent_exec_result(payload: object) -> AgentExecResultValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return AgentExecResultValidationResult(False, ("$: expected object",))

    required = {
        "schema",
        "run_id",
        "status",
        "exit_code",
        "signal",
        "duration_ms",
        "command",
        "command_redacted",
        "raw",
        "exposed",
        "diagnostics",
        "redacted",
        "output_truncated",
        "termination",
        "retry_count",
    }
    missing = sorted(required - set(payload))
    errors.extend(f"$.{name}: required" for name in missing)
    unknown = sorted(set(payload) - required)
    errors.extend(f"$.{name}: unknown field" for name in unknown)

    if payload.get("schema") != AGENT_EXEC_RESULT_CONTRACT_VERSION:
        errors.append("$.schema: unsupported contract version")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not _valid_run_id(run_id):
        errors.append("$.run_id: invalid run id")
    if payload.get("status") not in AGENT_EXEC_STATUSES:
        errors.append("$.status: invalid status")
    if payload.get("exit_code") is not None and not _is_int(payload.get("exit_code")):
        errors.append("$.exit_code: expected integer or null")
    signal = payload.get("signal")
    if signal is not None and (not _is_int(signal) or signal < 1):
        errors.append("$.signal: expected positive integer or null")
    duration = payload.get("duration_ms")
    if not _is_int(duration) or duration < 0:
        errors.append("$.duration_ms: expected non-negative integer")
    command = payload.get("command")
    if (
        not isinstance(command, list)
        or not command
        or len(command) > 256
        or any(not isinstance(item, str) for item in command)
    ):
        errors.append("$.command: expected 1..256 strings")
    for name in ("command_redacted", "redacted", "output_truncated"):
        if not isinstance(payload.get(name), bool):
            errors.append(f"$.{name}: expected boolean")

    _validate_count_block(
        payload.get("raw"),
        path="$.raw",
        keys=("stdout_bytes", "stderr_bytes"),
        errors=errors,
    )
    _validate_count_block(
        payload.get("exposed"),
        path="$.exposed",
        keys=("lines", "bytes"),
        errors=errors,
    )
    exposed = payload.get("exposed")
    if isinstance(exposed, dict):
        if _is_int(exposed.get("lines")) and exposed["lines"] > 120:
            errors.append("$.exposed.lines: exceeds 120")
        if _is_int(exposed.get("bytes")) and exposed["bytes"] > 24_576:
            errors.append("$.exposed.bytes: exceeds 24576")

    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        errors.append("$.diagnostics: expected object")
    else:
        expected = {"available", "truncated", "strategy", "line_count", "byte_count"}
        if set(diagnostics) != expected:
            errors.append("$.diagnostics: fields do not match contract")
        if not isinstance(diagnostics.get("available"), bool):
            errors.append("$.diagnostics.available: expected boolean")
        if not isinstance(diagnostics.get("truncated"), bool):
            errors.append("$.diagnostics.truncated: expected boolean")
        if diagnostics.get("strategy") not in AGENT_EXEC_DIAGNOSTIC_STRATEGIES:
            errors.append("$.diagnostics.strategy: invalid strategy")
        for key, maximum in (("line_count", 120), ("byte_count", 24_576)):
            value = diagnostics.get(key)
            if not _is_int(value) or value < 0 or value > maximum:
                errors.append(f"$.diagnostics.{key}: out of range")

    termination = payload.get("termination")
    if not isinstance(termination, dict):
        errors.append("$.termination: expected object")
    else:
        expected = {
            "requested",
            "method",
            "escalated",
            "group_state",
            "group_uncertain",
            "pipes_eof",
        }
        if set(termination) != expected:
            errors.append("$.termination: fields do not match contract")
        for key in ("requested", "escalated", "group_uncertain", "pipes_eof"):
            if not isinstance(termination.get(key), bool):
                errors.append(f"$.termination.{key}: expected boolean")
        for key in ("method", "group_state"):
            if not isinstance(termination.get(key), str):
                errors.append(f"$.termination.{key}: expected string")

    if payload.get("retry_count") != 0:
        errors.append("$.retry_count: base execution never retries")
    return AgentExecResultValidationResult(not errors, tuple(errors))


def _validate_count_block(
    value: object,
    *,
    path: str,
    keys: tuple[str, ...],
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return
    if set(value) != set(keys):
        errors.append(f"{path}: fields do not match contract")
    for key in keys:
        item = value.get(key)
        if not _is_int(item) or item < 0:
            errors.append(f"{path}.{key}: expected non-negative integer")


def _valid_run_id(value: str) -> bool:
    if len(value) != 32 or not value.startswith("AX-"):
        return False
    timestamp, separator, suffix = value[3:].partition("-")
    if separator != "-" or len(timestamp) != 16 or len(suffix) != 12:
        return False
    if timestamp[8] != "T" or timestamp[-1] != "Z":
        return False
    digits = timestamp[:8] + timestamp[9:15]
    return digits.isdigit() and all(char in "0123456789abcdef" for char in suffix)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
