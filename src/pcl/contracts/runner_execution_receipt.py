from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


RUNNER_EXECUTION_RECEIPT_CONTRACT_VERSION = "runner-execution-receipt/v1"
RUNNER_EXECUTION_RECEIPT_SCHEMA_RESOURCE = (
    "schemas/runner-execution-receipt-v1.schema.json"
)

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z$"
)
_RECEIPT_FIELDS = {
    "contract_version",
    "receipt_sha256",
    "attempt_id",
    "attempt_index",
    "previous_attempt_id",
    "previous_receipt_sha256",
    "cross_attempt_binding_sha256",
    "requested_argv_sha256",
    "spawned_argv_sha256",
    "cwd",
    "cwd_identity_sha256",
    "env_identity_sha256",
    "pid",
    "pgid",
    "started_at",
    "ended_at",
    "event_sequence",
    "event_frame_root_sha256",
    "dropped_count",
    "eof",
    "exit_code",
    "timed_out",
    "timeout_seconds",
    "spawn",
    "termination",
    "stdout_sha256",
    "stderr_sha256",
    "child_observation",
    "platform_capability",
}
_SPAWN_FIELDS = {"status", "error_kind"}
_TERMINATION_FIELDS = {
    "requested",
    "method",
    "escalated",
    "term_sent",
    "kill_sent",
    "group_state",
    "leader_alive",
    "pipes_eof",
}
_EOF_FIELDS = {"stdout", "stderr", "frames"}
_CHILD_OBSERVATION_FIELDS = {
    "authority",
    "status",
    "frames_received",
    "summary_sha256",
    "events_sha256",
}
_PLATFORM_CAPABILITY_FIELDS = {
    "os",
    "anonymous_pipe",
    "process_group",
    "status",
}


@dataclass(frozen=True)
class RunnerExecutionReceiptValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": RUNNER_EXECUTION_RECEIPT_CONTRACT_VERSION,
            "errors": list(self.errors),
            "ok": self.ok,
        }


def runner_execution_receipt_schema() -> dict[str, Any]:
    resource = files("pcl.contracts").joinpath(
        RUNNER_EXECUTION_RECEIPT_SCHEMA_RESOURCE
    )
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Runner execution receipt schema must be an object")
    return value


def load_runner_execution_receipt(path: str | Path) -> Any:
    return json.loads(
        Path(path).read_bytes(),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite_json_number,
    )


def canonical_runner_execution_receipt_json(
    receipt: Mapping[str, Any],
) -> str:
    return json.dumps(
        receipt,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compute_cross_attempt_binding_sha256(
    receipt: Mapping[str, Any],
) -> str:
    binding = {
        "attempt_id": receipt.get("attempt_id"),
        "attempt_index": receipt.get("attempt_index"),
        "previous_attempt_id": receipt.get("previous_attempt_id"),
        "previous_receipt_sha256": receipt.get("previous_receipt_sha256"),
        "requested_argv_sha256": receipt.get("requested_argv_sha256"),
        "cwd_identity_sha256": receipt.get("cwd_identity_sha256"),
        "env_identity_sha256": receipt.get("env_identity_sha256"),
    }
    return _sha256_json(binding)


def compute_runner_execution_receipt_sha256(
    receipt: Mapping[str, Any],
) -> str:
    content = dict(receipt)
    content.pop("receipt_sha256", None)
    return _sha256_json(content)


def finalize_runner_execution_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(receipt))
    result["cross_attempt_binding_sha256"] = compute_cross_attempt_binding_sha256(
        result
    )
    result["receipt_sha256"] = compute_runner_execution_receipt_sha256(result)
    return result


def serialized_runner_execution_receipt(receipt: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def validate_runner_execution_receipt(
    value: Any,
) -> RunnerExecutionReceiptValidationResult:
    errors: list[str] = []
    if not isinstance(value, dict):
        return RunnerExecutionReceiptValidationResult(("$: must be an object",))
    _collect_non_finite(value, "$", errors)
    _exact_fields(value, "$", _RECEIPT_FIELDS, errors)
    _equal(
        value.get("contract_version"),
        RUNNER_EXECUTION_RECEIPT_CONTRACT_VERSION,
        "$.contract_version",
        errors,
    )
    _sha(value.get("receipt_sha256"), "$.receipt_sha256", errors)
    _attempt_id(value.get("attempt_id"), "$.attempt_id", errors)
    _nonnegative_integer(value.get("attempt_index"), "$.attempt_index", errors)
    _optional_attempt_id(
        value.get("previous_attempt_id"), "$.previous_attempt_id", errors
    )
    _optional_sha(
        value.get("previous_receipt_sha256"),
        "$.previous_receipt_sha256",
        errors,
    )
    _sha(
        value.get("cross_attempt_binding_sha256"),
        "$.cross_attempt_binding_sha256",
        errors,
    )
    _sha(value.get("requested_argv_sha256"), "$.requested_argv_sha256", errors)
    _optional_sha(
        value.get("spawned_argv_sha256"),
        "$.spawned_argv_sha256",
        errors,
    )
    _nonempty_string(value.get("cwd"), "$.cwd", errors)
    _sha(value.get("cwd_identity_sha256"), "$.cwd_identity_sha256", errors)
    _sha(value.get("env_identity_sha256"), "$.env_identity_sha256", errors)
    _optional_nonnegative_integer(value.get("pid"), "$.pid", errors)
    _optional_nonnegative_integer(value.get("pgid"), "$.pgid", errors)
    _timestamp(value.get("started_at"), "$.started_at", errors)
    _timestamp(value.get("ended_at"), "$.ended_at", errors)
    _nonnegative_integer(value.get("event_sequence"), "$.event_sequence", errors)
    _sha(
        value.get("event_frame_root_sha256"),
        "$.event_frame_root_sha256",
        errors,
    )
    _nonnegative_integer(value.get("dropped_count"), "$.dropped_count", errors)
    _eof(value.get("eof"), errors)
    _optional_integer(value.get("exit_code"), "$.exit_code", errors)
    if not isinstance(value.get("timed_out"), bool):
        errors.append("$.timed_out: must be a boolean")
    _positive_integer(value.get("timeout_seconds"), "$.timeout_seconds", errors)
    _spawn(value.get("spawn"), errors)
    _termination(value.get("termination"), errors)
    _sha(value.get("stdout_sha256"), "$.stdout_sha256", errors)
    _sha(value.get("stderr_sha256"), "$.stderr_sha256", errors)
    _child_observation(value.get("child_observation"), errors)
    _platform_capability(value.get("platform_capability"), errors)

    if _sha256_value(value.get("cross_attempt_binding_sha256")):
        expected_binding = compute_cross_attempt_binding_sha256(value)
        if value.get("cross_attempt_binding_sha256") != expected_binding:
            errors.append(
                "$.cross_attempt_binding_sha256: does not match canonical attempt binding"
            )
    if _sha256_value(value.get("receipt_sha256")) and not _has_non_finite(value):
        expected_receipt = compute_runner_execution_receipt_sha256(value)
        if value.get("receipt_sha256") != expected_receipt:
            errors.append("$.receipt_sha256: does not match canonical receipt content")

    spawn = value.get("spawn")
    if isinstance(spawn, dict):
        spawned = spawn.get("status") == "spawned"
        if spawned and not _sha256_value(value.get("spawned_argv_sha256")):
            errors.append("$.spawned_argv_sha256: required for a spawned process")
        if not spawned and value.get("spawned_argv_sha256") is not None:
            errors.append("$.spawned_argv_sha256: must be null when spawn did not succeed")
        if spawned and value.get("pid") is None:
            errors.append("$.pid: required for a spawned process")
        if not spawned and value.get("pid") is not None:
            errors.append("$.pid: must be null when spawn did not succeed")
    eof = value.get("eof")
    termination = value.get("termination")
    if isinstance(eof, dict) and isinstance(termination, dict):
        if termination.get("pipes_eof") != (eof.get("stdout") and eof.get("stderr")):
            errors.append("$.termination.pipes_eof: does not match stdout/stderr EOF")
        if eof.get("frames") is not True and value.get("event_sequence") == 0:
            errors.append("$.event_sequence: incomplete frame collection must be explicit")
    if value.get("timed_out") is True and value.get("exit_code") is not None:
        errors.append("$.exit_code: timed out executions must not claim an exit code")
    if value.get("attempt_index") == 0 and (
        value.get("previous_attempt_id") is not None
        or value.get("previous_receipt_sha256") is not None
    ):
        errors.append("$: first attempt cannot bind a previous attempt")
    if value.get("attempt_index", 0) > 0 and (
        value.get("previous_attempt_id") is None
        or value.get("previous_receipt_sha256") is None
    ):
        errors.append("$: later attempt must bind its previous attempt")
    try:
        started = datetime.fromisoformat(str(value.get("started_at")).replace("Z", "+00:00"))
        ended = datetime.fromisoformat(str(value.get("ended_at")).replace("Z", "+00:00"))
    except ValueError:
        pass
    else:
        if ended < started:
            errors.append("$.ended_at: must not precede started_at")

    return RunnerExecutionReceiptValidationResult(tuple(sorted(set(errors))))


def _spawn(value: Any, errors: list[str]) -> None:
    path = "$.spawn"
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact_fields(value, path, _SPAWN_FIELDS, errors)
    if value.get("status") not in {"not_attempted", "spawned", "failed"}:
        errors.append(f"{path}.status: must be one of failed, not_attempted, spawned")
    if value.get("error_kind") not in {None, "not_found", "permission_denied", "os_error"}:
        errors.append(
            f"{path}.error_kind: must be one of not_found, os_error, permission_denied, or null"
        )
    if value.get("status") == "failed" and value.get("error_kind") is None:
        errors.append(f"{path}.error_kind: failed spawn requires an error kind")
    if value.get("status") == "spawned" and value.get("error_kind") is not None:
        errors.append(f"{path}.error_kind: spawned process requires null")


def _termination(value: Any, errors: list[str]) -> None:
    path = "$.termination"
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact_fields(value, path, _TERMINATION_FIELDS, errors)
    for field in ("requested", "escalated", "term_sent", "kill_sent", "leader_alive", "pipes_eof"):
        if not isinstance(value.get(field), bool):
            errors.append(f"{path}.{field}: must be a boolean")
    _nonempty_string(value.get("method"), f"{path}.method", errors, allow_empty=True)
    if value.get("group_state") not in {
        "not_started",
        "gone",
        "surviving",
        "unknown",
        "not_applicable",
    }:
        errors.append(
            f"{path}.group_state: must be one of gone, not_applicable, not_started, surviving, unknown"
        )


def _eof(value: Any, errors: list[str]) -> None:
    path = "$.eof"
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact_fields(value, path, _EOF_FIELDS, errors)
    for field in sorted(_EOF_FIELDS):
        if not isinstance(value.get(field), bool):
            errors.append(f"{path}.{field}: must be a boolean")


def _child_observation(value: Any, errors: list[str]) -> None:
    path = "$.child_observation"
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact_fields(value, path, _CHILD_OBSERVATION_FIELDS, errors)
    if value.get("authority") != "non_authoritative":
        errors.append(f"{path}.authority: must equal 'non_authoritative'")
    if value.get("status") not in {"received", "missing", "partial", "not_applicable"}:
        errors.append(
            f"{path}.status: must be one of missing, not_applicable, partial, received"
        )
    _nonnegative_integer(value.get("frames_received"), f"{path}.frames_received", errors)
    _optional_sha(value.get("summary_sha256"), f"{path}.summary_sha256", errors)
    _optional_sha(value.get("events_sha256"), f"{path}.events_sha256", errors)
    if value.get("status") == "missing" and value.get("frames_received") != 0:
        errors.append(f"{path}.frames_received: missing observation requires zero frames")
    if value.get("status") == "not_applicable" and value.get("frames_received") != 0:
        errors.append(f"{path}.frames_received: not_applicable requires zero frames")


def _platform_capability(value: Any, errors: list[str]) -> None:
    path = "$.platform_capability"
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return
    _exact_fields(value, path, _PLATFORM_CAPABILITY_FIELDS, errors)
    if value.get("os") not in {"posix", "windows", "other"}:
        errors.append(f"{path}.os: must be one of other, posix, windows")
    for field in ("anonymous_pipe", "process_group", "status"):
        if value.get(field) not in {"available", "not_applicable", "uncertain"}:
            errors.append(
                f"{path}.{field}: must be one of available, not_applicable, uncertain"
            )
    if value.get("os") == "windows":
        if value.get("anonymous_pipe") != "not_applicable":
            errors.append(
                f"{path}.anonymous_pipe: Windows capability must be not_applicable"
            )
        if value.get("process_group") != "not_applicable":
            errors.append(
                f"{path}.process_group: Windows capability must be not_applicable"
            )
    if value.get("os") == "posix" and value.get("process_group") != "uncertain":
        errors.append(
            f"{path}.process_group: POSIX process-group capability must be uncertain"
        )


def _exact_fields(
    value: Mapping[str, Any],
    path: str,
    fields: set[str],
    errors: list[str],
) -> None:
    missing = sorted(fields - set(value))
    unexpected = sorted(set(value) - fields)
    for field in missing:
        errors.append(f"{path}.{field}: is required")
    for field in unexpected:
        errors.append(f"{path}.{field}: additional property is not allowed")


def _attempt_id(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _ATTEMPT_ID.fullmatch(value) is None:
        errors.append(f"{path}: must be a non-empty attempt identifier")


def _optional_attempt_id(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _attempt_id(value, path, errors)


def _sha(value: Any, path: str, errors: list[str]) -> None:
    if not _sha256_value(value):
        errors.append(f"{path}: must be a sha256 digest")


def _optional_sha(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _sha(value, path, errors)


def _sha256_value(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _nonempty_string(
    value: Any,
    path: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, str) or (not allow_empty and not value):
        errors.append(f"{path}: must be a string")


def _nonnegative_integer(value: Any, path: str, errors: list[str]) -> None:
    if type(value) is not int or value < 0:
        errors.append(f"{path}: must be a non-negative integer")


def _optional_nonnegative_integer(value: Any, path: str, errors: list[str]) -> None:
    if value is not None:
        _nonnegative_integer(value, path, errors)


def _optional_integer(value: Any, path: str, errors: list[str]) -> None:
    if value is not None and type(value) is not int:
        errors.append(f"{path}: must be an integer or null")


def _positive_integer(value: Any, path: str, errors: list[str]) -> None:
    if type(value) is not int or value < 1:
        errors.append(f"{path}: must be a positive integer")


def _equal(value: Any, expected: Any, path: str, errors: list[str]) -> None:
    if value != expected:
        errors.append(f"{path}: must equal {expected!r}")


def _timestamp(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        errors.append(f"{path}: must be an RFC 3339 UTC timestamp")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: must be a real RFC 3339 UTC timestamp")


def _sha256_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _collect_non_finite(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite numbers are not allowed")
    elif isinstance(value, dict):
        for key, item in value.items():
            _collect_non_finite(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_non_finite(item, f"{path}[{index}]", errors)


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_non_finite(item) for item in value)
    return False


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


# Short aliases mirror the other contract modules and keep callers from having
# to repeat the versioned noun in every import.
runner_execution_receipt_sha256 = compute_runner_execution_receipt_sha256
finalize_runner_execution_receipt_document = finalize_runner_execution_receipt
validate_runner_execution_receipt_document = validate_runner_execution_receipt
