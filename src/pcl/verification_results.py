from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import signal
from typing import Any, Iterable, Mapping

from . import __version__


FINISH_CHECK_RESULT_CONTRACT_VERSION = "finish-check-result/v2"
RUNNER_RESULT_CONTRACT_VERSION = "runner-result/v1"
ASSERTION_RESULT_CONTRACT_VERSION = "assertion-result/v1"
VERIFICATION_ATTEMPT_IDENTITY_CONTRACT_VERSION = (
    "verification-attempt-identity/v1"
)
VERIFICATION_EXECUTION_IDENTITY_CONTRACT_VERSION = (
    "verification-execution-identity/v1"
)
STABILITY_EVALUATION_CONTRACT_VERSION = "stability-evaluation/v1"

_LOCK_FILE_NAMES = frozenset(
    {
        "Cargo.lock",
        "Gemfile.lock",
        "bun.lock",
        "bun.lockb",
        "composer.lock",
        "go.sum",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)
_LOCK_FILE_PREFIXES = ("requirements",)
_ASSERTION_STATUSES = frozenset(
    {"passed", "failed", "not_evaluated", "unknown"}
)
_STABILITY_STRATA = ("cold", "warm")


def build_finish_check_result(
    command: Mapping[str, Any],
    *,
    evidence_id: str,
    attempt_identity: Mapping[str, Any],
    stability_evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the additive v2 check result while retaining legacy fields."""

    runner_result, assertion_result, failure_phase, failure_kind = (
        _classify_command_result(command)
    )
    timed_out = runner_result["status"] == "timed_out"
    status = (
        "timed_out"
        if timed_out
        else "passed"
        if assertion_result["status"] == "passed"
        else "failed"
    )
    return {
        "contract_version": FINISH_CHECK_RESULT_CONTRACT_VERSION,
        "evidence_id": evidence_id,
        "command": str(command["resolved_command"]),
        "status": status,
        "exit_code": command.get("exit_code"),
        "reason": _legacy_reason(
            runner_status=str(runner_result["status"]),
            assertion_status=str(assertion_result["status"]),
        ),
        "stdout_path": command.get("stdout_path"),
        "stderr_path": command.get("stderr_path"),
        "stdout": command.get("stdout"),
        "stderr": command.get("stderr"),
        "output_truncated": bool(command.get("output_truncated")),
        "redacted": bool(command.get("redacted")),
        "permission_contract": command.get("permission_contract"),
        "termination": command.get("termination"),
        "failure_phase": failure_phase,
        "failure_kind": failure_kind,
        "runner_result": runner_result,
        "assertion_result": assertion_result,
        "observability": dict(command.get("observability", {})),
        "attempt_identity": dict(attempt_identity),
        "stability_evaluation": dict(stability_evaluation),
        "reuse": dict(command.get("reuse", {})),
    }


def build_verification_attempt_identity(
    *,
    input_manifest: Mapping[str, Any],
    command: Mapping[str, Any],
    finish_policy: Mapping[str, Any],
    timeout_seconds: int,
    max_output_bytes: int,
    stability_stratum: str,
) -> dict[str, Any]:
    """Build a deterministic identity for deciding whether attempts are comparable."""

    if stability_stratum not in _STABILITY_STRATA:
        raise ValueError(
            f"stability_stratum must be one of {', '.join(_STABILITY_STRATA)}"
        )
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be at least 1")

    permission_contract = command.get("permission_contract")
    if not isinstance(permission_contract, Mapping):
        permission_contract = {}
    environment = permission_contract.get("environment")
    if not isinstance(environment, Mapping):
        environment = {}
    execution_context = environment.get("execution_context")
    if not isinstance(execution_context, Mapping):
        execution_context = {}

    executed_argv = command.get("executed_argv")
    if not isinstance(executed_argv, list):
        executed_argv = command.get("argv")
    argv = [str(part) for part in executed_argv] if isinstance(executed_argv, list) else []
    semantic: dict[str, Any] = {
        "contract_version": VERIFICATION_ATTEMPT_IDENTITY_CONTRACT_VERSION,
        "identity_sha256": "",
        "input_manifest_sha256": input_manifest.get("manifest_sha256"),
        "lock_inputs_sha256": _lock_inputs_sha256(input_manifest),
        "command": {
            "argv": argv,
            "scope": command.get("scope"),
            "config_key": command.get("config_key"),
        },
        "toolchain": _toolchain_identity(argv),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "environment": {
            "sha256": environment.get("sha256"),
            "inheritance": environment.get("inheritance"),
            "worker_sha256": execution_context.get("worker_sha256"),
            "shard_sha256": execution_context.get("shard_sha256"),
            "seed_sha256": execution_context.get("seed_sha256"),
            "values_recorded": False,
        },
        "execution": {
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": max_output_bytes,
            "stability_stratum": stability_stratum,
            "cache": {
                "mode": stability_stratum,
                "manifest_sha256": None,
            },
        },
        "finish_policy_sha256": _canonical_sha256(finish_policy),
    }
    semantic["identity_sha256"] = _canonical_sha256(
        {key: value for key, value in semantic.items() if key != "identity_sha256"}
    )
    execution_semantic = {
        "contract_version": VERIFICATION_EXECUTION_IDENTITY_CONTRACT_VERSION,
        "input_manifest_sha256": semantic["input_manifest_sha256"],
        "lock_inputs_sha256": semantic["lock_inputs_sha256"],
        "command": {
            "argv": argv,
            "scope": command.get("scope"),
            "kind": command.get("kind"),
        },
        "toolchain": semantic["toolchain"],
        "platform": semantic["platform"],
        "environment": semantic["environment"],
        "execution": {
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": max_output_bytes,
        },
        "finish_execution_policy_sha256": _canonical_sha256(
            _execution_policy(finish_policy)
        ),
    }
    semantic["execution_identity_contract_version"] = (
        VERIFICATION_EXECUTION_IDENTITY_CONTRACT_VERSION
    )
    semantic["execution_identity_sha256"] = _canonical_sha256(
        execution_semantic
    )
    return semantic


def evaluate_stability(
    attempts: Iterable[Mapping[str, Any]],
    *,
    minimum_consecutive_passes: int = 2,
    maximum_attempts: int = 3,
    required_strata: Iterable[str] = _STABILITY_STRATA,
) -> dict[str, Any]:
    """Evaluate compatible attempts without treating one green exit as reproducible."""

    if minimum_consecutive_passes < 1:
        raise ValueError("minimum_consecutive_passes must be at least 1")
    if maximum_attempts < minimum_consecutive_passes:
        raise ValueError(
            "maximum_attempts must be at least minimum_consecutive_passes"
        )
    required = tuple(dict.fromkeys(str(item) for item in required_strata))
    invalid_strata = sorted(set(required) - set(_STABILITY_STRATA))
    if invalid_strata:
        raise ValueError(
            "required_strata contains unsupported values: "
            + ", ".join(invalid_strata)
        )

    attempt_rows = [dict(attempt) for attempt in attempts]
    identities = {
        identity_sha256
        for attempt in attempt_rows
        if isinstance((identity := attempt.get("attempt_identity")), Mapping)
        and (identity_sha256 := _comparable_identity_sha256(identity)) is not None
    }
    statuses = [_attempt_assertion_status(attempt) for attempt in attempt_rows]
    strata = [_attempt_stratum(attempt) for attempt in attempt_rows]
    result = {
        "contract_version": STABILITY_EVALUATION_CONTRACT_VERSION,
        "status": "stability_required",
        "reproducible": False,
        "identity_sha256": next(iter(identities)) if len(identities) == 1 else None,
        "policy": {
            "minimum_consecutive_passes": minimum_consecutive_passes,
            "maximum_attempts": maximum_attempts,
            "required_strata": list(required),
        },
        "attempt_count": len(attempt_rows),
        "remaining_attempts": max(0, maximum_attempts - len(attempt_rows)),
        "consecutive_passes": _trailing_pass_count(statuses),
        "mixed_outcomes": len(set(statuses)) > 1,
        "outcomes": {
            status: statuses.count(status)
            for status in sorted(_ASSERTION_STATUSES)
        },
        "strata": {
            stratum: {
                "attempts": strata.count(stratum),
                "passed": sum(
                    1
                    for index, value in enumerate(strata)
                    if value == stratum and statuses[index] == "passed"
                ),
                "failed": sum(
                    1
                    for index, value in enumerate(strata)
                    if value == stratum and statuses[index] != "passed"
                ),
            }
            for stratum in _STABILITY_STRATA
        },
        "reasons": [],
    }

    recorded_identities = {
        _comparable_identity_sha256(identity)
        if isinstance((identity := attempt.get("attempt_identity")), Mapping)
        else None
        for attempt in attempt_rows
    }
    if len(identities) != 1 or recorded_identities != identities:
        if attempt_rows:
            result["status"] = "incompatible_attempts"
            result["reasons"] = ["attempt_identity_mismatch"]
        else:
            result["reasons"] = ["no_attempts"]
        return result

    passed_strata = {
        strata[index]
        for index, status in enumerate(statuses)
        if status == "passed"
    }
    all_passed = bool(statuses) and all(status == "passed" for status in statuses)
    policy_satisfied = (
        all_passed
        and result["consecutive_passes"] >= minimum_consecutive_passes
        and set(required).issubset(passed_strata)
    )
    if policy_satisfied:
        result["status"] = "stable"
        result["reproducible"] = True
        return result

    reasons: list[str] = []
    if not all_passed:
        reasons.append("assertions_not_all_passed")
    if result["mixed_outcomes"]:
        reasons.append("mixed_assertion_outcomes")
    if result["consecutive_passes"] < minimum_consecutive_passes:
        reasons.append("insufficient_consecutive_passes")
    if not set(required).issubset(passed_strata):
        reasons.append("missing_required_strata")
    if len(attempt_rows) >= maximum_attempts:
        reasons.append("attempt_budget_exhausted")
        result["status"] = "incomplete_flaky"
    result["reasons"] = reasons
    return result


def _classify_command_result(
    command: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str | None, str | None]:
    exit_code = command.get("exit_code")
    timed_out = bool(command.get("timed_out"))
    legacy_failure_kind = str(command.get("failure_kind") or "")
    spawn_error_kind = str(command.get("spawn_error_kind") or "")
    artifact_collection = command.get("artifact_collection")
    if not isinstance(artifact_collection, Mapping):
        artifact_collection = {
            "status": "collected",
            "stdout": bool(command.get("stdout_path")),
            "stderr": bool(command.get("stderr_path")),
        }
    artifact_collection = dict(artifact_collection)
    signal_value = _signal_value(exit_code)
    observability = command.get("observability")
    observability_failure = (
        str(observability.get("failure_kind") or "observer_unavailable")
        if isinstance(observability, Mapping)
        and observability.get("eligible") is not True
        else None
    )

    if artifact_collection.get("status") != "collected":
        runner_status = "collection_failed"
        assertion_status = "unknown"
        failure_phase = "collect"
        failure_kind = "infrastructure"
    elif legacy_failure_kind == "spawn_error":
        runner_status = "spawn_failed"
        assertion_status = "not_evaluated"
        failure_phase = "spawn"
        failure_kind = (
            "dependency"
            if spawn_error_kind == "not_found"
            else "infrastructure"
        )
    elif timed_out:
        runner_status = "timed_out"
        assertion_status = "not_evaluated"
        failure_phase = "execute"
        failure_kind = "timeout"
    elif signal_value is not None:
        runner_status = "signaled"
        assertion_status = "not_evaluated"
        failure_phase = "execute"
        failure_kind = "crash"
    elif exit_code is None:
        runner_status = "crashed"
        assertion_status = "not_evaluated"
        failure_phase = "execute"
        failure_kind = "crash"
    elif observability_failure and exit_code == 0:
        runner_status = "completed"
        assertion_status = "unknown"
        failure_phase = "observe"
        failure_kind = str(observability_failure)
    elif exit_code == 0:
        runner_status = "completed"
        assertion_status = "passed"
        failure_phase = None
        failure_kind = None
    else:
        runner_status = "completed"
        assertion_status = "failed"
        failure_phase = "assert"
        failure_kind = "assertion"

    runner_result = {
        "contract_version": RUNNER_RESULT_CONTRACT_VERSION,
        "status": runner_status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "signal": signal_value,
        "duration_seconds": command.get("duration_seconds"),
        "spawn_error_kind": spawn_error_kind or None,
        "artifact_collection": artifact_collection,
        "termination": command.get("termination"),
        "legacy_failure_kind": legacy_failure_kind or None,
        "observability_status": (
            observability.get("status")
            if isinstance(observability, Mapping)
            else None
        ),
        "observability_failure_kind": (
            str(observability_failure) if observability_failure else None
        ),
    }
    assertion_result = {
        "contract_version": ASSERTION_RESULT_CONTRACT_VERSION,
        "status": assertion_status,
        "source": "process_exit",
        "exit_code": exit_code,
        "reason": _assertion_reason(assertion_status, runner_status),
    }
    return runner_result, assertion_result, failure_phase, failure_kind


def _signal_value(exit_code: Any) -> dict[str, Any] | None:
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code >= 0:
        return None
    number = -exit_code
    try:
        name = signal.Signals(number).name
    except ValueError:
        name = None
    return {"number": number, "name": name}


def _assertion_reason(assertion_status: str, runner_status: str) -> str | None:
    if assertion_status == "passed":
        return None
    if assertion_status == "failed":
        return "guarded_command_nonzero_exit"
    if assertion_status == "unknown":
        if runner_status == "completed":
            return "runner_observability_unknown"
        return "artifact_collection_failed"
    return f"runner_{runner_status}"


def _legacy_reason(*, runner_status: str, assertion_status: str) -> str | None:
    if runner_status == "timed_out":
        return "Timed out during guarded execution."
    if runner_status == "spawn_failed":
        return "Guarded command could not be spawned."
    if runner_status == "signaled":
        return "Guarded command was terminated by a signal."
    if runner_status == "collection_failed":
        return "Guarded command artifacts could not be collected."
    if runner_status == "crashed":
        return "Guarded command did not produce an exit result."
    if assertion_status == "unknown":
        return "Runner observability did not establish a trustworthy result."
    if assertion_status == "failed":
        return "Guarded command returned a non-zero exit code."
    return None


def _lock_inputs_sha256(input_manifest: Mapping[str, Any]) -> str:
    entries = input_manifest.get("entries")
    if not isinstance(entries, list):
        entries = []
    locks = [
        {
            "path": entry.get("path"),
            "kind": entry.get("kind"),
            "sha256": entry.get("sha256"),
            "symlink_target": entry.get("symlink_target"),
        }
        for entry in entries
        if isinstance(entry, Mapping) and _is_lock_path(str(entry.get("path") or ""))
    ]
    return _canonical_sha256(locks)


def _is_lock_path(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in _LOCK_FILE_NAMES or (
        name.startswith(_LOCK_FILE_PREFIXES) and name.endswith((".txt", ".in"))
    )


def _toolchain_identity(argv: list[str]) -> dict[str, Any]:
    executable = argv[0] if argv else ""
    resolved = shutil.which(executable) if executable else None
    executable_path = Path(resolved).resolve() if resolved else None
    executable_stat: dict[str, Any] | None = None
    if executable_path is not None:
        try:
            stat_result = executable_path.stat()
        except OSError:
            executable_stat = None
        else:
            executable_stat = {
                "size": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
            }
    module_name = (
        argv[2].split(".", 1)[0]
        if len(argv) >= 3 and argv[1] == "-m"
        else None
    )
    return {
        "pcl_version": __version__,
        "python_version": platform.python_version(),
        "executable": {
            "name": Path(executable).name if executable else None,
            "path": str(executable_path) if executable_path is not None else None,
            "version": _distribution_version(
                Path(executable).name if executable else None
            ),
            "stat": executable_stat,
        },
        "module": {
            "name": module_name,
            "version": _distribution_version(module_name),
        }
        if module_name
        else None,
    }


def _distribution_version(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _attempt_assertion_status(attempt: Mapping[str, Any]) -> str:
    assertion = attempt.get("assertion_result")
    status = assertion.get("status") if isinstance(assertion, Mapping) else None
    if status not in _ASSERTION_STATUSES:
        return "unknown"
    return str(status)


def _comparable_identity_sha256(identity: Mapping[str, Any]) -> str | None:
    value = identity.get("execution_identity_sha256")
    if not isinstance(value, str):
        value = identity.get("identity_sha256")
    return value if isinstance(value, str) else None


def _attempt_stratum(attempt: Mapping[str, Any]) -> str:
    value = str(attempt.get("stratum") or "")
    return value if value in _STABILITY_STRATA else "cold"


def _trailing_pass_count(statuses: list[str]) -> int:
    count = 0
    for status in reversed(statuses):
        if status != "passed":
            break
        count += 1
    return count


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _execution_policy(finish_policy: Mapping[str, Any]) -> dict[str, Any]:
    commands = finish_policy.get("commands")
    unique_commands: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    if isinstance(commands, list):
        for command in commands:
            if not isinstance(command, Mapping):
                continue
            argv_value = command.get("argv")
            argv = (
                tuple(str(part) for part in argv_value)
                if isinstance(argv_value, list)
                else ()
            )
            key = (
                str(command.get("scope") or ""),
                str(command.get("kind") or ""),
                argv,
            )
            unique_commands[key] = {
                "scope": command.get("scope"),
                "kind": command.get("kind"),
                "argv": list(argv),
            }
    return {
        "contract_version": finish_policy.get("contract_version"),
        "commands": [
            unique_commands[key]
            for key in sorted(unique_commands)
        ],
        "declared_output_patterns": finish_policy.get(
            "declared_output_patterns",
            [],
        ),
        "timeout_seconds": finish_policy.get("timeout_seconds"),
        "max_output_bytes": finish_policy.get("max_output_bytes"),
    }
