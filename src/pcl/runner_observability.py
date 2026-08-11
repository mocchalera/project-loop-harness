from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import threading
import time
from typing import Any

from .runner_execution_receipt import write_child_frame

# Bind the real monotonic clock once. Finish injects this module as a live
# pytest plugin, so suite tests that monkeypatch ``time.monotonic`` (for
# example locks timeout fixtures) must not stop the observer with
# StopIteration mid-session.
_MONOTONIC = time.monotonic


RUNNER_OBSERVABILITY_CONTRACT_VERSION = "runner-observability/v1"
RUNNER_OBSERVABILITY_OBSERVER_VERSION = "runner-observability/v1"
PYTEST_PLUGIN_MODULE = "pcl.runner_observability"
OBSERVABILITY_SUMMARY_ENV = "PCL_RUNNER_OBSERVABILITY_SUMMARY"
OBSERVABILITY_EVENTS_ENV = "PCL_RUNNER_OBSERVABILITY_EVENTS"
MAX_EVENT_COUNT = 16_384
MAX_EVENT_LOG_BYTES = 2 * 1_024 * 1_024
MAX_EVENT_LINE_BYTES = 16_384
MAX_OVERFLOW_SUMMARY_BYTES = 16_384
HEARTBEAT_INTERVAL_SECONDS = 1.0
_OBSERVABILITY_STATUSES = frozenset({"complete", "partial", "unavailable"})
_OBSERVABILITY_COMMAND_KINDS = frozenset({"pytest", "non_pytest"})
_OBSERVABILITY_FAILURE_KINDS = frozenset(
    {
        "artifact_integrity_failed",
        "collection_incomplete",
        "observer_unavailable",
        "process_group_uncertain",
        "provenance_mismatch",
        "timeout_budget_exhausted",
    }
)
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_pytest_argv(argv: list[str]) -> bool:
    """Return whether argv invokes pytest directly or through ``python -m``."""

    for index, value in enumerate(argv):
        name = Path(str(value)).name.lower()
        if name in {"pytest", "pytest.exe"}:
            return True
        if value == "-m" and index + 1 < len(argv):
            module = str(argv[index + 1]).strip()
            if module == "pytest" or module.startswith("pytest."):
                return True
    return False


def inject_pytest_hook(argv: list[str]) -> tuple[list[str], bool]:
    """Inject the local observer without changing the configured command."""

    copied = [str(part) for part in argv]
    if not is_pytest_argv(copied):
        return copied, False
    if any(
        copied[index] == "-p"
        and index + 1 < len(copied)
        and copied[index + 1] == PYTEST_PLUGIN_MODULE
        for index in range(len(copied))
    ):
        return copied, False
    module_index = next(
        (
            index
            for index, value in enumerate(copied[:-1])
            if value == "-m" and copied[index + 1] == "pytest"
        ),
        None,
    )
    insert_at = module_index + 2 if module_index is not None else 1
    return (
        copied[:insert_at] + ["-p", PYTEST_PLUGIN_MODULE] + copied[insert_at:],
        True,
    )


def collect_runner_provenance(
    argv: list[str], *, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    environment = os.environ if env is None else env
    module_path = Path(__file__).resolve()
    module_sha256 = hash_file(module_path)
    return {
        "pcl_module": {
            "path": str(module_path),
            "sha256": module_sha256,
        },
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "version": platform.python_version(),
        },
        "pytest": {
            "executable": _pytest_executable(argv),
            "version": _distribution_version("pytest") if is_pytest_argv(argv) else None,
        },
        "pythonpath_sha256": sha256_text(str(environment.get("PYTHONPATH", ""))),
        "observer": {
            "version": RUNNER_OBSERVABILITY_OBSERVER_VERSION,
            "module": PYTEST_PLUGIN_MODULE,
            "sha256": module_sha256,
        },
    }


def observability_environment(
    summary_path: Path,
    events_path: Path,
    *,
    frame_fd: int | None = None,
) -> dict[str, str]:
    environment = {
        OBSERVABILITY_SUMMARY_ENV: str(summary_path),
        OBSERVABILITY_EVENTS_ENV: str(events_path),
    }
    if frame_fd is not None:
        environment["PCL_RUNNER_OBSERVABILITY_FRAME_FD"] = str(frame_fd)
    return environment


def emit_child_observation_frame(
    event: str,
    *,
    phase: str = "observe",
    source: str = "child",
    **fields: Any,
) -> bool:
    """Emit derived child diagnostics without creating a receipt authority."""

    return write_child_frame(
        {
            "event": str(event),
            "phase": str(phase),
            "source": str(source),
            "at": _utc_now(),
            **fields,
        }
    )


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def hash_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65_536), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"
    except OSError:
        return None


def normalize_observability_paths(
    observation: dict[str, Any], *, root: Path
) -> dict[str, Any]:
    """Make paths stable for command/result JSON without resolving user data."""

    result = json.loads(json.dumps(observation, ensure_ascii=False))
    root = root.resolve()
    for key in ("summary_path", "events_path"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = _relative_or_original(Path(value), root)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        for item in artifacts.values():
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                item["path"] = _relative_or_original(Path(item["path"]), root)
    return result


def observability_for_result_json(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the result-side view without a recursive result self-hash."""

    result = json.loads(json.dumps(dict(observation), ensure_ascii=False))
    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        result_artifact = artifacts.get("result")
        if isinstance(result_artifact, dict):
            result_artifact["sha256"] = None
    return result


def verify_runner_observability(
    summary_path: Path,
    *,
    root: Path | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
    allow_pending_result: bool = False,
) -> dict[str, Any]:
    """Validate a persisted sidecar and its referenced artifacts fail-closed."""

    root_path = (root or summary_path.parent).resolve()
    try:
        raw = summary_path.read_bytes()
        payload = _strict_json_loads(raw)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "failure_kind": "artifact_integrity_failed",
            "issues": [f"summary_unreadable:{exc.__class__.__name__}"],
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "failure_kind": "artifact_integrity_failed",
            "issues": ["summary_not_object"],
        }
    if payload.get("contract_version") != RUNNER_OBSERVABILITY_CONTRACT_VERSION:
        return {
            "ok": False,
            "failure_kind": "artifact_integrity_failed",
            "issues": ["summary_contract_mismatch"],
        }

    issues = _validate_summary_payload(
        payload,
        summary_path=summary_path,
        root=root_path,
        allow_pending_result=allow_pending_result,
    )
    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping):
        if provenance.get("status") == "mismatch":
            issues.append("provenance_mismatch")
        if expected_provenance is not None and provenance.get("expected") != dict(
            expected_provenance
        ):
            issues.append("provenance_expected_mismatch")

    if issues:
        return {
            "ok": False,
            "failure_kind": (
                "provenance_mismatch"
                if any("provenance" in issue for issue in issues)
                else "artifact_integrity_failed"
            ),
            "issues": sorted(set(issues)),
            "payload": payload,
        }
    eligible = payload.get("eligible") is True
    return {
        "ok": eligible,
        "failure_kind": None if eligible else str(payload.get("failure_kind") or "observer_unavailable"),
        "issues": [] if eligible else [str(payload.get("failure_kind") or "observer_unavailable")],
        "payload": payload,
    }


def _validate_summary_payload(
    payload: Mapping[str, Any],
    *,
    summary_path: Path,
    root: Path,
    allow_pending_result: bool,
) -> list[str]:
    """Validate the v1 summary shape before trusting any result claims."""

    issues: list[str] = []
    required_summary_fields = (
        "contract_version",
        "status",
        "eligible",
        "failure_kind",
        "source",
        "command_kind",
        "requires_nodeid",
        "summary_path",
        "events_path",
        "last_started",
        "last_completed",
        "last_phase",
        "collection",
        "heartbeat",
        "budget",
        "process_group",
        "termination",
        "provenance",
        "event_log",
        "artifacts",
    )
    for field in required_summary_fields:
        if field not in payload:
            issues.append(f"summary_field_missing:{field}")

    if payload.get("contract_version") != RUNNER_OBSERVABILITY_CONTRACT_VERSION:
        issues.append("summary_contract_mismatch")

    status = payload.get("status")
    eligible = payload.get("eligible")
    failure_kind = payload.get("failure_kind")
    command_kind = payload.get("command_kind")
    source = payload.get("source")
    requires_nodeid = payload.get("requires_nodeid")
    if not isinstance(status, str) or status not in _OBSERVABILITY_STATUSES:
        issues.append("summary_field_invalid:status")
    if not isinstance(eligible, bool):
        issues.append("summary_field_invalid:eligible")
    if failure_kind is not None and (
        not isinstance(failure_kind, str) or not failure_kind
    ):
        issues.append("summary_field_invalid:failure_kind")
    elif isinstance(failure_kind, str) and failure_kind not in _OBSERVABILITY_FAILURE_KINDS:
        issues.append("summary_field_invalid:failure_kind")
    if not isinstance(source, str) or not source:
        issues.append("summary_field_invalid:source")
    if not isinstance(command_kind, str) or command_kind not in _OBSERVABILITY_COMMAND_KINDS:
        issues.append("summary_field_invalid:command_kind")
    if not isinstance(requires_nodeid, bool):
        issues.append("summary_field_invalid:requires_nodeid")

    summary_value = payload.get("summary_path")
    events_value = payload.get("events_path")
    if not isinstance(summary_value, str) or not summary_value:
        issues.append("summary_path_missing")
        summary_reference = None
    else:
        summary_reference = _resolve_artifact_path(summary_value, root)
        if summary_reference.resolve() != summary_path.resolve():
            issues.append("summary_path_reference_mismatch")
    if not isinstance(events_value, str) or not events_value:
        issues.append("events_path_missing")
        events_reference = None
    else:
        events_reference = _resolve_artifact_path(events_value, root)

    _validate_node_event(payload.get("last_started"), "last_started", issues)
    _validate_node_event(payload.get("last_completed"), "last_completed", issues)
    _validate_node_event(payload.get("last_phase"), "last_phase", issues)
    collection = payload.get("collection")
    if isinstance(collection, Mapping):
        _validate_integer_or_none(collection, "collected_count", "collection", issues)
        _validate_nonnegative_integer(collection, "started_count", "collection", issues)
        _validate_nonnegative_integer(collection, "completed_count", "collection", issues)
        _validate_boolean(collection, "collection_finished", "collection", issues)
    else:
        issues.append("summary_field_invalid:collection")

    heartbeat = payload.get("heartbeat")
    if isinstance(heartbeat, Mapping):
        _validate_nonnegative_integer(heartbeat, "count", "heartbeat", issues)
        _validate_optional_string(heartbeat, "first_at", "heartbeat", issues)
        _validate_optional_string(heartbeat, "last_at", "heartbeat", issues)
        _validate_number_or_none(heartbeat, "interval_seconds", "heartbeat", issues)
    else:
        issues.append("summary_field_invalid:heartbeat")

    budget = payload.get("budget")
    if isinstance(budget, Mapping):
        _validate_number(budget, "elapsed_seconds", "budget", issues)
        _validate_positive_integer(budget, "timeout_seconds", "budget", issues)
        _validate_boolean(budget, "exhausted", "budget", issues)
        _validate_number(budget, "overshoot_seconds", "budget", issues)
    else:
        issues.append("summary_field_invalid:budget")

    process_group = payload.get("process_group")
    if isinstance(process_group, Mapping):
        _validate_string(process_group, "state", "process_group", issues)
        _validate_boolean(process_group, "pipes_eof", "process_group", issues)
        _validate_boolean(process_group, "uncertain", "process_group", issues)
        _validate_boolean(process_group, "term_sent", "process_group", issues)
        _validate_boolean(process_group, "kill_sent", "process_group", issues)
    else:
        issues.append("summary_field_invalid:process_group")

    termination = payload.get("termination")
    if isinstance(termination, Mapping):
        _validate_boolean(termination, "requested", "termination", issues)
        _validate_string(termination, "method", "termination", issues)
        _validate_boolean(termination, "escalated", "termination", issues)
        _validate_string(termination, "group_state", "termination", issues)
        _validate_boolean(termination, "pipes_eof", "termination", issues)
    else:
        issues.append("summary_field_invalid:termination")

    provenance = payload.get("provenance")
    if isinstance(provenance, Mapping):
        provenance_status = provenance.get("status")
        if provenance_status not in {"matched", "mismatch", "unavailable"}:
            issues.append("summary_field_invalid:provenance.status")
        if not isinstance(provenance.get("expected"), Mapping):
            issues.append("summary_field_invalid:provenance.expected")
        observed = provenance.get("observed")
        if observed is not None and not isinstance(observed, Mapping):
            issues.append("summary_field_invalid:provenance.observed")
    else:
        issues.append("summary_field_invalid:provenance")

    event_log = payload.get("event_log")
    event_log_issues: list[Any] = []
    if isinstance(event_log, Mapping):
        _validate_nonnegative_integer(event_log, "count", "event_log", issues)
        _validate_nonnegative_integer(event_log, "dropped_count", "event_log", issues)
        _validate_boolean(event_log, "bounded", "event_log", issues)
        _validate_positive_integer(event_log, "max_events", "event_log", issues)
        _validate_positive_integer(event_log, "max_bytes", "event_log", issues)
        raw_event_log_issues = event_log.get("issues")
        if not isinstance(raw_event_log_issues, list):
            issues.append("summary_field_invalid:event_log.issues")
        else:
            event_log_issues = raw_event_log_issues
    else:
        issues.append("summary_field_invalid:event_log")

    overflow_progress = payload.get("overflow_progress")
    if overflow_progress is not None:
        _validate_overflow_progress(overflow_progress, issues)

    artifacts = payload.get("artifacts")
    required_artifacts = ("stdout", "stderr", "result", "summary", "events")
    if not isinstance(artifacts, Mapping):
        issues.append("artifacts_missing")
        artifacts = {}
    else:
        for name in sorted(set(artifacts) - set(required_artifacts)):
            issues.append(f"artifact_unexpected:{name}")
        for name in required_artifacts:
            if name not in artifacts:
                issues.append(f"artifact_missing_field:{name}")
                continue
            item = artifacts[name]
            if not isinstance(item, Mapping):
                issues.append(f"artifact_not_object:{name}")
                continue
            for field in ("path", "sha256"):
                if field not in item:
                    issues.append(f"artifact_field_missing:{name}.{field}")
            path_value = item.get("path")
            recorded = item.get("sha256")
            if (
                allow_pending_result
                and name == "result"
                and path_value is None
                and recorded is None
            ):
                # execute_guarded_process writes the runner sidecar before
                # finish creates result.json.  Finish must verify this
                # reference again after finalization.
                continue
            if not isinstance(path_value, str) or not path_value:
                issues.append(f"artifact_path_invalid:{name}")
            if not _is_sha256(recorded):
                issues.append(f"artifact_hash_invalid:{name}")
            if isinstance(path_value, str) and path_value:
                artifact_path = _resolve_artifact_path(path_value, root)
                actual = hash_file(artifact_path)
                if actual is None:
                    issues.append(f"artifact_missing:{name}")
                elif name != "summary" and _is_sha256(recorded) and actual != recorded:
                    issues.append(f"artifact_hash_mismatch:{name}")

    summary_item = artifacts.get("summary")
    if isinstance(summary_item, Mapping):
        summary_item_path = summary_item.get("path")
        if summary_reference is not None and summary_item_path != summary_value:
            issues.append("summary_artifact_reference_mismatch")
        if "sha256" in summary_item and _is_sha256(summary_item.get("sha256")):
            if sha256_bytes(_json_bytes(_summary_digest_payload(payload))) != summary_item[
                "sha256"
            ]:
                issues.append("artifact_hash_mismatch:summary")
    events_item = artifacts.get("events")
    if isinstance(events_item, Mapping):
        events_item_path = events_item.get("path")
        if events_reference is not None and events_item_path != events_value:
            issues.append("events_artifact_reference_mismatch")

    if events_reference is not None:
        events = _read_event_log(events_reference)
        issues.extend(events["issues"])
    else:
        events = {"events": [], "issues": []}
    if event_log_issues:
        issues.extend(
            f"event_log_issue_unrecorded:{issue}"
            for issue in events["issues"]
            if issue not in event_log_issues
        )
    if isinstance(event_log, Mapping) and isinstance(event_log.get("issues"), list):
        if sorted(str(issue) for issue in event_log["issues"]) != sorted(
            str(issue) for issue in events["issues"]
        ):
            issues.append("event_log_issues_mismatch")

    if isinstance(eligible, bool) and isinstance(status, str):
        if eligible and status != "complete":
            issues.append("summary_semantic_inconsistent:eligible_status")
        if not eligible and status == "complete":
            issues.append("summary_semantic_inconsistent:eligible_status")
        if eligible and failure_kind is not None:
            issues.append("summary_semantic_inconsistent:eligible_failure_kind")
        if not eligible and status == "unavailable" and not isinstance(failure_kind, str):
            issues.append("summary_semantic_inconsistent:unavailable_failure_kind")

    if isinstance(command_kind, str) and isinstance(source, str):
        expected_source = "pytest_hook" if command_kind == "pytest" else "watchdog"
        if source != expected_source:
            issues.append("summary_semantic_inconsistent:source_command_kind")
    if isinstance(process_group, Mapping) and isinstance(termination, Mapping):
        if process_group.get("state") != termination.get("group_state"):
            issues.append("summary_semantic_inconsistent:termination_state")
        if process_group.get("pipes_eof") != termination.get("pipes_eof"):
            issues.append("summary_semantic_inconsistent:termination_pipes_eof")
        expected_uncertain = process_group.get("state") in {"unknown", "surviving"} or (
            process_group.get("pipes_eof") is False
        )
        if process_group.get("uncertain") != expected_uncertain:
            issues.append("summary_semantic_inconsistent:process_group_uncertain")

    if eligible is True:
        if isinstance(budget, Mapping) and budget.get("exhausted") is not False:
            issues.append("summary_semantic_inconsistent:budget")
        if isinstance(process_group, Mapping) and (
            process_group.get("state") not in {"gone", "not_applicable"}
            or process_group.get("pipes_eof") is not True
            or process_group.get("uncertain") is not False
        ):
            issues.append("summary_semantic_inconsistent:process_group")
        if isinstance(provenance, Mapping) and provenance.get("status") != "matched":
            issues.append("summary_semantic_inconsistent:provenance")
        if isinstance(event_log, Mapping) and event_log.get("issues") != []:
            issues.append("summary_semantic_inconsistent:event_log")
        if (
            command_kind == "pytest"
            and isinstance(collection, Mapping)
            and collection.get("collection_finished") is not True
        ):
            issues.append("summary_semantic_inconsistent:collection")

    return sorted(set(issues))


def _validate_node_event(
    value: Any, name: str, issues: list[str]
) -> None:
    if not isinstance(value, Mapping):
        issues.append(f"summary_field_invalid:{name}")
        return
    nodeid = value.get("nodeid")
    if nodeid is not None and not isinstance(nodeid, str):
        issues.append(f"summary_field_invalid:{name}.nodeid")
    if not isinstance(value.get("phase"), str):
        issues.append(f"summary_field_invalid:{name}.phase")
    at = value.get("at")
    if at is not None and not isinstance(at, str):
        issues.append(f"summary_field_invalid:{name}.at")


def _validate_boolean(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    if not isinstance(value.get(field), bool):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_string(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    if not isinstance(value.get(field), str):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_optional_string(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    field_value = value.get(field)
    if field_value is not None and not isinstance(field_value, str):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_number(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    field_value = value.get(field)
    if (
        not isinstance(field_value, (int, float))
        or isinstance(field_value, bool)
        or not math.isfinite(float(field_value))
    ):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_number_or_none(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    field_value = value.get(field)
    if field_value is not None and (
        not isinstance(field_value, (int, float))
        or isinstance(field_value, bool)
        or not math.isfinite(float(field_value))
    ):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_overflow_progress(value: Any, issues: list[str]) -> None:
    prefix = "overflow_progress"
    if not isinstance(value, Mapping):
        issues.append(f"summary_field_invalid:{prefix}")
        return
    if value.get("contract_version") != "runner-observability-overflow-progress/v1":
        issues.append(f"summary_field_invalid:{prefix}.contract_version")
    if value.get("active") is not True:
        issues.append(f"summary_field_invalid:{prefix}.active")
    if value.get("green_authority") is not False:
        issues.append(f"summary_field_invalid:{prefix}.green_authority")
    if value.get("authority") not in {
        "parent_observed_child_diagnostic",
        "child_diagnostic",
    }:
        issues.append(f"summary_field_invalid:{prefix}.authority")
    if value.get("integrity") not in {"pending", "verified", "unavailable"}:
        issues.append(f"summary_field_invalid:{prefix}.integrity")
    _validate_integer_or_none(value, "dropped_event_count", prefix, issues)
    progress = value.get("latest_progress")
    if progress is not None and (
        not isinstance(progress, Mapping)
        or _validated_overflow_progress(progress) is None
    ):
        issues.append(f"summary_field_invalid:{prefix}.latest_progress")
    heartbeat = value.get("latest_heartbeat")
    if heartbeat is not None:
        if not isinstance(heartbeat, Mapping):
            issues.append(f"summary_field_invalid:{prefix}.latest_heartbeat")
        else:
            _validate_string(heartbeat, "at", f"{prefix}.latest_heartbeat", issues)
            _validate_number(
                heartbeat,
                "elapsed_seconds",
                f"{prefix}.latest_heartbeat",
                issues,
            )
            _validate_boolean(
                heartbeat,
                "process_alive",
                f"{prefix}.latest_heartbeat",
                issues,
            )


def _validate_nonnegative_integer(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    field_value = value.get(field)
    if (
        not isinstance(field_value, int)
        or isinstance(field_value, bool)
        or field_value < 0
    ):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_positive_integer(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    field_value = value.get(field)
    if (
        not isinstance(field_value, int)
        or isinstance(field_value, bool)
        or field_value < 1
    ):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _validate_integer_or_none(
    value: Mapping[str, Any], field: str, prefix: str, issues: list[str]
) -> None:
    field_value = value.get(field)
    if field_value is not None and (
        not isinstance(field_value, int)
        or isinstance(field_value, bool)
        or field_value < 0
    ):
        issues.append(f"summary_field_invalid:{prefix}.{field}")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def finalize_persisted_observability(
    observation: Mapping[str, Any],
    *,
    root: Path,
    result_path: Path,
    result_sha256: str | None = None,
) -> dict[str, Any]:
    """Rebase and finalize the sidecar after completion Evidence gets its ID."""

    normalized = normalize_observability_paths(dict(observation), root=root)
    summary_value = normalized.get("summary_path")
    events_value = normalized.get("events_path")
    summary_path = _resolve_artifact_path(str(summary_value or ""), root.resolve())
    events_path = _resolve_artifact_path(str(events_value or ""), root.resolve())
    try:
        summary_payload = _strict_json_loads(summary_path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        summary_payload = {
            "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
            "status": "unavailable",
            "eligible": False,
            "failure_kind": "artifact_integrity_failed",
            "source": normalized.get("source"),
            "command_kind": normalized.get("command_kind"),
            "requires_nodeid": normalized.get("requires_nodeid"),
            "collection": {},
            "heartbeat": {},
            "budget": {},
            "process_group": {},
            "termination": {},
            "provenance": normalized.get("provenance", {}),
            "event_log": {},
            "artifacts": {},
        }
    if not isinstance(summary_payload, dict):
        summary_payload = {
            "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
            "status": "unavailable",
            "eligible": False,
            "failure_kind": "artifact_integrity_failed",
            "artifacts": {},
        }

    parsed = _read_event_log(events_path)
    issues = list(parsed["issues"])
    normalized_artifacts = normalized.get("artifacts")
    if not isinstance(normalized_artifacts, Mapping):
        normalized_artifacts = {}
    artifacts = summary_payload.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        summary_payload["artifacts"] = artifacts
    for name in ("stdout", "stderr"):
        item = normalized_artifacts.get(name)
        if isinstance(item, Mapping):
            artifact_path = _resolve_artifact_path(str(item.get("path") or ""), root.resolve())
            actual = hash_file(artifact_path)
            if actual is None:
                issues.append(f"artifact_missing:{name}")
            elif isinstance(item.get("sha256"), str) and actual != item["sha256"]:
                issues.append(f"artifact_hash_mismatch:{name}")
            artifacts[name] = {
                "path": _relative_or_original(artifact_path, root.resolve()),
                "sha256": actual,
            }
    result_relative = _relative_or_original(result_path, root.resolve())
    artifacts["result"] = {"path": result_relative, "sha256": result_sha256}
    artifacts["events"] = {
        "path": _relative_or_original(events_path, root.resolve()),
        "sha256": hash_file(events_path),
    }
    artifacts["summary"] = {
        "path": _relative_or_original(summary_path, root.resolve()),
        "sha256": None,
    }
    summary_payload["summary_path"] = artifacts["summary"]["path"]
    summary_payload["events_path"] = artifacts["events"]["path"]
    summary_payload["event_log"] = {
        **(
            summary_payload.get("event_log")
            if isinstance(summary_payload.get("event_log"), dict)
            else {}
        ),
        "count": len(parsed["events"]),
        "issues": sorted(set(issues)),
    }
    if issues:
        summary_payload["eligible"] = False
        summary_payload["status"] = "unavailable"
        summary_payload["failure_kind"] = "artifact_integrity_failed"
    _write_summary_payload(summary_path, summary_payload)
    return normalize_observability_paths(summary_payload, root=root)


def _is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _event_log_has_capacity(current_size: int, encoded_length: int) -> bool:
    # Parent watchdog and child hook are the only writers. Reserving one
    # maximum line means simultaneous append decisions still cannot cross the
    # advertised byte cap, without introducing a new lock artifact.
    return current_size + encoded_length <= MAX_EVENT_LOG_BYTES - MAX_EVENT_LINE_BYTES


def _validated_overflow_progress(value: Mapping[str, Any]) -> dict[str, Any] | None:
    nodeid = value.get("nodeid")
    phase = value.get("phase")
    at = value.get("at")
    elapsed = value.get("elapsed_seconds")
    completed = value.get("completed_count")
    if not isinstance(nodeid, str) or not nodeid:
        return None
    if not isinstance(phase, str) or not phase:
        return None
    if not isinstance(at, str) or not at:
        return None
    if (
        not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        return None
    if completed is not None and not _is_nonnegative_integer(completed):
        return None
    return {
        "at": at,
        "completed_count": completed,
        "elapsed_seconds": float(elapsed),
        "nodeid": nodeid,
        "phase": phase,
    }


def _overflow_progress_from_observation(
    observation: Mapping[str, Any],
) -> dict[str, Any] | None:
    if observation.get("source") != "pytest_hook":
        return None
    nodeid = observation.get("nodeid")
    if nodeid is None:
        return None
    phase = observation.get("phase")
    at = observation.get("at")
    elapsed = observation.get("elapsed_seconds")
    completed = observation.get("completed_count")
    validated = _validated_overflow_progress(
        {
            "nodeid": nodeid,
            "phase": phase,
            "at": at,
            "elapsed_seconds": elapsed,
            "completed_count": completed,
        }
    )
    if validated is None:
        raise ValueError("overflow progress fields are malformed or non-finite")
    return validated


class RunnerObservabilityRecorder:
    """Parent-side bounded event recorder for one guarded completion check."""

    def __init__(
        self,
        *,
        summary_path: Path,
        events_path: Path,
        argv: list[str],
        timeout_seconds: int,
        env: Mapping[str, str],
    ) -> None:
        self.summary_path = summary_path
        self.events_path = events_path
        self.argv = list(argv)
        self.timeout_seconds = timeout_seconds
        self.command_kind = "pytest" if is_pytest_argv(argv) else "non_pytest"
        self.requires_nodeid = self.command_kind == "pytest" and "--collect-only" not in argv
        self.started_monotonic = _MONOTONIC()
        self.started_at = _utc_now()
        self.expected_provenance = collect_runner_provenance(argv, env=env)
        self._sequence = 0
        self._event_count = 0
        self._dropped_count = 0
        self._lock = threading.Lock()
        self._parent_observation_channel = False
        self._last_parent_sequence = 0
        self._last_child_sequence = 0
        self._child_dropped_count = 0
        self._overflow_active = False
        self._overflow_latest_progress: dict[str, Any] | None = None
        self._overflow_latest_heartbeat: dict[str, Any] | None = None
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.write_bytes(b"")

    def set_parent_observation_channel(self, available: bool) -> None:
        """Record whether child diagnostics cross a parent-owned channel."""

        with self._lock:
            self._parent_observation_channel = bool(available)

    def observe_child_observation(
        self, observation: Mapping[str, Any], parent_sequence: int
    ) -> None:
        """Checkpoint post-cap child progress without granting green authority."""

        progress = _overflow_progress_from_observation(observation)
        persisted = observation.get("event_log_persisted")
        dropped_count = observation.get("event_log_dropped_count")
        child_sequence = observation.get("sequence")
        if persisted is not True and persisted is not False:
            return
        if not _is_nonnegative_integer(dropped_count):
            raise ValueError("event_log_dropped_count must be a nonnegative integer")
        if not _is_nonnegative_integer(parent_sequence) or parent_sequence < 1:
            raise ValueError("parent_sequence must be a positive integer")
        if not _is_nonnegative_integer(child_sequence) or child_sequence < 1:
            raise ValueError("child sequence must be a positive integer")
        with self._lock:
            if parent_sequence <= self._last_parent_sequence:
                raise ValueError("parent observation sequence must be monotonic")
            if child_sequence != self._last_child_sequence + 1:
                raise ValueError("child observation sequence must be contiguous")
            expected_dropped_count = self._child_dropped_count + (not persisted)
            if dropped_count != expected_dropped_count:
                raise ValueError("event_log_dropped_count is inconsistent")
            self._last_parent_sequence = parent_sequence
            self._last_child_sequence = child_sequence
            self._child_dropped_count = expected_dropped_count
            self._overflow_active = self._overflow_active or not persisted or dropped_count > 0
            if progress is not None:
                if self._overflow_latest_progress is not None:
                    completed = self._overflow_latest_progress.get("completed_count")
                    if progress.get("completed_count") is None:
                        progress["completed_count"] = completed
                self._overflow_latest_progress = progress
            if self._overflow_active:
                self._write_overflow_checkpoint_locked(integrity="pending")

    def start(self) -> None:
        self.emit(
            "runner_started",
            phase="spawn",
            source="watchdog",
            command_kind=self.command_kind,
            requires_nodeid=self.requires_nodeid,
            provenance=self.expected_provenance,
        )
        self.emit("heartbeat", phase="spawn", source="watchdog", process_alive=False)

    def emit(self, event: str, *, phase: str, source: str, **fields: Any) -> None:
        record = {
            "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
            "sequence": self._next_sequence(),
            "event": event,
            "phase": phase,
            "source": source,
            "at": _utc_now(),
            "elapsed_seconds": round(_MONOTONIC() - self.started_monotonic, 6),
            **fields,
        }
        encoded = _json_bytes(record) + b"\n"
        with self._lock:
            if event == "heartbeat":
                self._overflow_latest_heartbeat = {
                    "at": record["at"],
                    "elapsed_seconds": record["elapsed_seconds"],
                    "process_alive": bool(fields.get("process_alive")),
                }
            if len(encoded) > MAX_EVENT_LINE_BYTES:
                self._dropped_count += 1
                self._overflow_active = True
                self._write_overflow_checkpoint_locked(integrity="pending")
                return
            try:
                current_size = self.events_path.stat().st_size
                if (
                    self._event_count >= MAX_EVENT_COUNT
                    or not _event_log_has_capacity(current_size, len(encoded))
                ):
                    self._dropped_count += 1
                    self._overflow_active = True
                    self._write_overflow_checkpoint_locked(integrity="pending")
                    return
                with self.events_path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                self._event_count += 1
            except OSError:
                self._dropped_count += 1
                self._overflow_active = True
                self._write_overflow_checkpoint_locked(integrity="pending")
            else:
                if self._overflow_active and event == "heartbeat":
                    self._write_overflow_checkpoint_locked(integrity="pending")

    def start_heartbeat(self, process: Any) -> tuple[threading.Event, threading.Thread]:
        stop_event = threading.Event()

        def run() -> None:
            while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
                self.emit(
                    "heartbeat",
                    phase="execute",
                    source="watchdog",
                    process_alive=process.poll() is None,
                )

        worker = threading.Thread(
            target=run,
            name="pcl-runner-observability-heartbeat",
            daemon=True,
        )
        worker.start()
        return stop_event, worker

    def finalize(
        self,
        *,
        stdout: Mapping[str, Any],
        stderr: Mapping[str, Any],
        exit_code: int | None,
        timed_out: bool,
        duration_seconds: float,
        termination: Mapping[str, Any],
        pipes_eof: bool,
        result_path: str | None = None,
        result_sha256: str | None = None,
        parent_observation_integrity: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._parent_observation_channel:
            with self._lock:
                self._merge_child_checkpoint_locked()
        self.emit(
            "process_group_final",
            phase="terminate" if timed_out else "complete",
            source="watchdog",
            state=termination.get("group_state"),
            leader_exit_code=exit_code,
        )
        self.emit(
            "pipes_eof",
            phase="collect",
            source="watchdog",
            stdout=bool(pipes_eof),
            stderr=bool(pipes_eof),
        )
        parsed = _read_event_log(self.events_path)
        events = parsed["events"]
        issues = list(parsed["issues"])
        observed_provenance = _observed_provenance(events)
        provenance_status = "matched"
        if observed_provenance is None and self.command_kind == "pytest":
            provenance_status = "unavailable"
        elif observed_provenance is not None and not _provenance_equal(
            self.expected_provenance, observed_provenance
        ):
            provenance_status = "mismatch"

        collection = _collection_summary(events)
        heartbeat = _heartbeat_summary(events, duration_seconds)
        last_started = _last_event(events, "test_started")
        last_completed = _last_event(events, "test_completed")
        last_phase = _last_phase_event(events)
        group_state = str(termination.get("group_state") or "unknown")
        process_group_uncertain = group_state in {"unknown", "surviving"} or not pipes_eof
        integrity_failure = bool(issues)
        failure_kind = _observability_failure_kind(
            command_kind=self.command_kind,
            requires_nodeid=self.requires_nodeid,
            collection=collection,
            last_started=last_started,
            last_completed=last_completed,
            hook_loaded=any(event.get("event") == "hook_loaded" for event in events),
            provenance_status=provenance_status,
            timed_out=timed_out,
            process_group_uncertain=process_group_uncertain,
            integrity_failure=integrity_failure,
            exit_code=exit_code,
        )
        eligible = failure_kind is None and exit_code == 0 and not timed_out
        status = "complete" if eligible else "partial"
        if integrity_failure or (
            self.command_kind == "pytest"
            and not any(event.get("event") == "hook_loaded" for event in events)
        ):
            status = "unavailable"

        elapsed = float(duration_seconds)
        budget = {
            "elapsed_seconds": round(elapsed, 6),
            "timeout_seconds": self.timeout_seconds,
            "exhausted": timed_out or elapsed >= self.timeout_seconds,
            "overshoot_seconds": round(max(0.0, elapsed - self.timeout_seconds), 6),
        }
        artifacts = {
            "stdout": _artifact(stdout.get("path"), stdout.get("sha256")),
            "stderr": _artifact(stderr.get("path"), stderr.get("sha256")),
            "result": {"path": result_path, "sha256": result_sha256},
            "summary": {"path": str(self.summary_path), "sha256": None},
            "events": {
                "path": str(self.events_path),
                "sha256": hash_file(self.events_path),
            },
        }
        summary: dict[str, Any] = {
            "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
            "status": status,
            "eligible": eligible,
            "source": "pytest_hook" if self.command_kind == "pytest" else "watchdog",
            "failure_kind": failure_kind,
            "command_kind": self.command_kind,
            "requires_nodeid": self.requires_nodeid,
            "summary_path": str(self.summary_path),
            "events_path": str(self.events_path),
            "last_started": _node_event(last_started),
            "last_completed": _node_event(last_completed),
            "last_phase": _node_event(last_phase),
            "collection": collection,
            "heartbeat": heartbeat,
            "budget": budget,
            "process_group": {
                "state": group_state,
                "pipes_eof": pipes_eof,
                "uncertain": process_group_uncertain,
                "term_sent": bool(termination.get("term_sent")),
                "kill_sent": bool(termination.get("kill_sent")),
            },
            "termination": dict(termination),
            "artifacts": artifacts,
            "provenance": {
                "status": provenance_status,
                "expected": self.expected_provenance,
                "observed": observed_provenance,
            },
            "event_log": {
                "count": len(events),
                "dropped_count": self._dropped_count + self._child_dropped_count,
                "bounded": True,
                "max_events": MAX_EVENT_COUNT,
                "max_bytes": MAX_EVENT_LOG_BYTES,
                "issues": sorted(set(issues)),
            },
        }
        overflow_progress = self._sealed_overflow_progress(parent_observation_integrity)
        if overflow_progress is not None:
            summary["overflow_progress"] = overflow_progress
        self._write_summary(summary)
        return normalize_observability_paths(summary, root=Path.cwd())

    def _next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def _write_summary(self, summary: dict[str, Any]) -> None:
        _write_summary_payload(self.summary_path, summary)

    def _overflow_progress_payload(self, *, integrity: str) -> dict[str, Any]:
        dropped_event_count: int | None = self._dropped_count + self._child_dropped_count
        if integrity == "unavailable" and self._parent_observation_channel:
            dropped_event_count = None
        return {
            "contract_version": "runner-observability-overflow-progress/v1",
            "active": True,
            "authority": (
                "parent_observed_child_diagnostic"
                if self._parent_observation_channel
                else "child_diagnostic"
            ),
            "green_authority": False,
            "integrity": integrity,
            "dropped_event_count": dropped_event_count,
            "latest_progress": self._overflow_latest_progress,
            "latest_heartbeat": self._overflow_latest_heartbeat,
        }

    def _write_overflow_checkpoint_locked(self, *, integrity: str) -> None:
        if not self._parent_observation_channel:
            self._merge_child_checkpoint_locked()
        payload = {
            "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
            "overflow_progress": self._overflow_progress_payload(integrity=integrity),
        }
        rendered = _json_bytes(payload) + b"\n"
        if len(rendered) > MAX_OVERFLOW_SUMMARY_BYTES:
            raise ValueError("overflow progress checkpoint exceeds its bound")
        _atomic_replace_bytes(self.summary_path, rendered)

    def _merge_child_checkpoint_locked(self) -> None:
        checkpoint = _read_overflow_checkpoint(self.summary_path)
        if checkpoint is None or checkpoint.get("authority") != "child_diagnostic":
            return
        dropped = checkpoint.get("dropped_event_count")
        if _is_nonnegative_integer(dropped):
            self._child_dropped_count = max(self._child_dropped_count, dropped)
        progress = checkpoint.get("latest_progress")
        if isinstance(progress, Mapping):
            validated = _validated_overflow_progress(progress)
            if validated is not None:
                current_elapsed = (
                    self._overflow_latest_progress or {}
                ).get("elapsed_seconds", -1.0)
                if validated["elapsed_seconds"] >= current_elapsed:
                    self._overflow_latest_progress = validated
        self._overflow_active = True

    def _sealed_overflow_progress(
        self, parent_observation_integrity: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        if not self._overflow_active:
            return None
        transport_ok = (
            self._parent_observation_channel
            and isinstance(parent_observation_integrity, Mapping)
            and parent_observation_integrity.get("frames_eof") is True
            and parent_observation_integrity.get("dropped_count") == 0
            and parent_observation_integrity.get("partial_frame") is False
            and parent_observation_integrity.get("reader_error") is False
            and parent_observation_integrity.get("limit_exceeded") is False
        )
        return self._overflow_progress_payload(
            integrity="verified" if transport_ok else "unavailable"
        )


class _PytestEventSink:
    def __init__(self, summary_path: Path, events_path: Path) -> None:
        self.summary_path = summary_path
        self.events_path = events_path
        self.frame_fd = _frame_fd_from_environment()
        self.started_monotonic = _MONOTONIC()
        self.sequence = 0
        self.event_count = 0
        self.dropped_count = 0
        self.collection_count: int | None = None
        self.started_count = 0
        self.completed_count = 0
        self._lock = threading.Lock()
        self._overflow_latest_progress: dict[str, Any] | None = None

    def emit(self, event: str, *, phase: str, **fields: Any) -> None:
        with self._lock:
            self.sequence += 1
            record = {
                "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
                "sequence": self.sequence,
                "event": event,
                "phase": phase,
                "source": "pytest_hook",
                "at": _utc_now(),
                "elapsed_seconds": round(_MONOTONIC() - self.started_monotonic, 6),
                **fields,
            }
            encoded = _json_bytes(record) + b"\n"
            persisted = False
            try:
                if len(encoded) > MAX_EVENT_LINE_BYTES or (
                    self.event_count >= MAX_EVENT_COUNT
                    or not _event_log_has_capacity(
                        self.events_path.stat().st_size, len(encoded)
                    )
                ):
                    self.dropped_count += 1
                else:
                    with self.events_path.open("ab") as stream:
                        stream.write(encoded)
                        stream.flush()
                    self.event_count += 1
                    persisted = True
            except OSError:
                self.dropped_count += 1
            transported = {
                **record,
                "event_log_persisted": persisted,
                "event_log_dropped_count": self.dropped_count,
            }
            if self.frame_fd is not None:
                # The parent assigns the authoritative sequence/root. This
                # transports diagnostics only; it cannot produce green proof.
                write_child_frame(transported, fd=self.frame_fd)
            elif self.dropped_count:
                self._write_child_overflow_checkpoint(transported)

    def _write_child_overflow_checkpoint(self, observation: Mapping[str, Any]) -> None:
        progress = _overflow_progress_from_observation(observation)
        if progress is not None:
            if (
                self._overflow_latest_progress is not None
                and progress.get("completed_count") is None
            ):
                progress["completed_count"] = self._overflow_latest_progress.get(
                    "completed_count"
                )
            self._overflow_latest_progress = progress
        payload = {
            "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
            "overflow_progress": {
                "contract_version": "runner-observability-overflow-progress/v1",
                "active": True,
                "authority": "child_diagnostic",
                "green_authority": False,
                "integrity": "pending",
                "dropped_event_count": self.dropped_count,
                "latest_progress": self._overflow_latest_progress,
                "latest_heartbeat": None,
            },
        }
        rendered = _json_bytes(payload) + b"\n"
        if len(rendered) <= MAX_OVERFLOW_SUMMARY_BYTES:
            _atomic_replace_bytes(self.summary_path, rendered)

    def close(self) -> None:
        if self.frame_fd is None:
            return
        try:
            os.close(self.frame_fd)
        except OSError:
            pass
        self.frame_fd = None


_PYTEST_SINK: _PytestEventSink | None = None


def pytest_configure(config: Any) -> None:
    global _PYTEST_SINK
    summary_value = os.environ.get(OBSERVABILITY_SUMMARY_ENV)
    events_value = os.environ.get(OBSERVABILITY_EVENTS_ENV)
    if not summary_value or not events_value:
        _PYTEST_SINK = None
        return
    _PYTEST_SINK = _PytestEventSink(Path(summary_value), Path(events_value))
    _PYTEST_SINK.emit(
        "hook_loaded",
        phase="configure",
        provenance=collect_runner_provenance(["pytest", *sys.argv[1:]]),
    )


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    if _PYTEST_SINK is not None:
        _PYTEST_SINK.collection_count = len(items)
        _PYTEST_SINK.emit(
            "collection_progress",
            phase="collection",
            collected_count=len(items),
        )


def pytest_collection_finish(session: Any) -> None:
    if _PYTEST_SINK is not None:
        count = len(getattr(session, "items", ()))
        _PYTEST_SINK.collection_count = count
        _PYTEST_SINK.emit(
            "collection_finished",
            phase="collection",
            collected_count=count,
            collection_finished=True,
        )


def pytest_runtest_logstart(nodeid: str, location: Any) -> None:
    if _PYTEST_SINK is not None:
        _PYTEST_SINK.started_count += 1
        _PYTEST_SINK.emit(
            "test_started",
            phase="execute",
            nodeid=str(nodeid),
            started_count=_PYTEST_SINK.started_count,
        )


def pytest_runtest_logreport(report: Any) -> None:
    if _PYTEST_SINK is None:
        return
    nodeid = str(getattr(report, "nodeid", "")) or None
    phase = str(getattr(report, "when", "unknown"))
    _PYTEST_SINK.emit(
        "test_phase",
        phase=phase,
        nodeid=nodeid,
        outcome=str(getattr(report, "outcome", "unknown")),
    )
    if phase == "call":
        _PYTEST_SINK.completed_count += 1
        _PYTEST_SINK.emit(
            "test_completed",
            phase=phase,
            nodeid=nodeid,
            completed_count=_PYTEST_SINK.completed_count,
            outcome=str(getattr(report, "outcome", "unknown")),
        )


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    if _PYTEST_SINK is not None:
        _PYTEST_SINK.emit(
            "session_finished",
            phase="finish",
            exit_code=int(exitstatus),
            collected_count=_PYTEST_SINK.collection_count,
            started_count=_PYTEST_SINK.started_count,
            completed_count=_PYTEST_SINK.completed_count,
        )
        _PYTEST_SINK.close()


def _observability_failure_kind(
    *,
    command_kind: str,
    requires_nodeid: bool,
    collection: Mapping[str, Any],
    last_started: Mapping[str, Any] | None,
    last_completed: Mapping[str, Any] | None,
    hook_loaded: bool,
    provenance_status: str,
    timed_out: bool,
    process_group_uncertain: bool,
    integrity_failure: bool,
    exit_code: int | None,
) -> str | None:
    if timed_out:
        return "timeout_budget_exhausted"
    if integrity_failure:
        return "artifact_integrity_failed"
    if provenance_status == "mismatch":
        return "provenance_mismatch"
    if process_group_uncertain:
        return "process_group_uncertain"
    if command_kind == "pytest":
        if not hook_loaded or provenance_status == "unavailable":
            return "observer_unavailable"
        if collection.get("collection_finished") is not True:
            return "collection_incomplete"
        if requires_nodeid and collection.get("collected_count", 0) and (
            last_started is None or last_completed is None
        ):
            return "observer_unavailable"
    if exit_code != 0:
        return None
    return None


def _collection_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    collected_count: int | None = None
    collection_finished = False
    started_count = 0
    completed_count = 0
    for event in events:
        if event.get("event") in {"collection_progress", "collection_finished"}:
            value = event.get("collected_count")
            if isinstance(value, int) and not isinstance(value, bool):
                collected_count = value
            collection_finished = collection_finished or event.get("event") == "collection_finished"
        elif event.get("event") == "test_started":
            started_count += 1
        elif event.get("event") == "test_completed":
            completed_count += 1
    return {
        "collected_count": collected_count,
        "started_count": started_count,
        "completed_count": completed_count,
        "collection_finished": collection_finished,
    }


def _heartbeat_summary(events: list[dict[str, Any]], duration_seconds: float) -> dict[str, Any]:
    heartbeats = [event for event in events if event.get("event") == "heartbeat"]
    first = heartbeats[0].get("at") if heartbeats else None
    last = heartbeats[-1].get("at") if heartbeats else None
    return {
        "first_at": first,
        "last_at": last,
        "count": len(heartbeats),
        "interval_seconds": round(
            duration_seconds / max(1, len(heartbeats) - 1), 6
        )
        if heartbeats
        else None,
    }


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return None


def _last_phase_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event") in {"test_phase", "test_started", "test_completed"}:
            return event
    return None


def _node_event(event: Mapping[str, Any] | None) -> dict[str, Any]:
    if event is None:
        return {"nodeid": None, "phase": "unavailable", "at": None}
    return {
        "nodeid": event.get("nodeid"),
        "phase": event.get("phase") or "unavailable",
        "at": event.get("at"),
    }


def _artifact(path: Any, sha256: Any) -> dict[str, Any]:
    return {
        "path": str(path) if isinstance(path, (str, Path)) else None,
        "sha256": str(sha256) if isinstance(sha256, str) else None,
    }


def _observed_provenance(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("event") == "hook_loaded" and isinstance(
            event.get("provenance"), dict
        ):
            return dict(event["provenance"])
    return None


def _provenance_equal(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> bool:
    expected_copy = json.loads(json.dumps(dict(expected), ensure_ascii=False))
    observed_copy = json.loads(json.dumps(dict(observed), ensure_ascii=False))
    for value in (expected_copy, observed_copy):
        pcl_module = value.get("pcl_module")
        if not isinstance(pcl_module, dict):
            return False
        path = pcl_module.get("path")
        if not isinstance(path, str) or not path:
            return False
        pcl_module["path"] = "<relocatable-pcl-module>"
    return expected_copy == observed_copy


def _read_event_log(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"events": [], "issues": [f"events_unreadable:{exc.__class__.__name__}"]}
    issues: list[str] = []
    if len(raw) > MAX_EVENT_LOG_BYTES:
        issues.append("events_exceed_bound")
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line) > MAX_EVENT_LINE_BYTES:
            issues.append(f"event_line_exceeds_bound:{line_number}")
            continue
        try:
            value = _strict_json_loads(line)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            issues.append(f"event_json_invalid:{line_number}")
            continue
        if not isinstance(value, dict):
            issues.append(f"event_not_object:{line_number}")
            continue
        events.append(value)
    return {"events": events, "issues": issues}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def _strict_json_loads(value: bytes | str) -> Any:
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite_json_number,
    )


def _read_overflow_checkpoint(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_OVERFLOW_SUMMARY_BYTES:
        return None
    try:
        payload = _strict_json_loads(raw)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    checkpoint = payload.get("overflow_progress")
    if not isinstance(checkpoint, Mapping):
        return None
    return dict(checkpoint)


def _summary_digest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove self-references before hashing the persisted summary."""

    without_self = _strict_json_loads(_json_bytes(dict(payload)))
    artifacts = without_self.get("artifacts")
    if isinstance(artifacts, dict):
        summary_item = artifacts.get("summary")
        if isinstance(summary_item, dict):
            summary_item["sha256"] = None
        result_item = artifacts.get("result")
        if isinstance(result_item, dict):
            # The result hash is stored in the sidecar, while result.json
            # carries a null self-reference to keep both artifacts finite.
            result_item["sha256"] = None
    return without_self


def _write_summary_payload(path: Path, payload: dict[str, Any]) -> bytes:
    summary_item = payload.setdefault("artifacts", {}).setdefault("summary", {})
    if isinstance(summary_item, dict):
        summary_item["sha256"] = None
    digest = sha256_bytes(_json_bytes(_summary_digest_payload(payload)))
    if isinstance(summary_item, dict):
        summary_item["sha256"] = digest
    rendered = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_replace_bytes(path, rendered)
    return rendered


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    """Persist a complete replacement with closed handles before replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _pytest_executable(argv: list[str]) -> str | None:
    for index, value in enumerate(argv):
        if value == "-m" and index + 1 < len(argv) and argv[index + 1] == "pytest":
            resolved = shutil.which("pytest")
            return str(Path(resolved).resolve()) if resolved else None
        if Path(str(value)).name.lower() in {"pytest", "pytest.exe"}:
            resolved = shutil.which(str(value)) or str(value)
            return str(Path(resolved).resolve())
    return None


def _relative_or_original(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except (OSError, ValueError):
        return str(path)


def _resolve_artifact_path(value: str, root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _frame_fd_from_environment() -> int | None:
    value = os.environ.get("PCL_RUNNER_OBSERVABILITY_FRAME_FD")
    if value is None:
        return None
    try:
        fd = int(value)
    except ValueError:
        return None
    if fd < 0:
        return None
    try:
        return os.dup(fd)
    except OSError:
        return None
