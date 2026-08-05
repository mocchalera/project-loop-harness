from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import threading
import time
from typing import Any


RUNNER_OBSERVABILITY_CONTRACT_VERSION = "runner-observability/v1"
RUNNER_OBSERVABILITY_OBSERVER_VERSION = "runner-observability/v1"
PYTEST_PLUGIN_MODULE = "pcl.runner_observability"
OBSERVABILITY_SUMMARY_ENV = "PCL_RUNNER_OBSERVABILITY_SUMMARY"
OBSERVABILITY_EVENTS_ENV = "PCL_RUNNER_OBSERVABILITY_EVENTS"
MAX_EVENT_COUNT = 16_384
MAX_EVENT_LOG_BYTES = 2 * 1_024 * 1_024
MAX_EVENT_LINE_BYTES = 16_384
HEARTBEAT_INTERVAL_SECONDS = 1.0


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
    summary_path: Path, events_path: Path
) -> dict[str, str]:
    return {
        OBSERVABILITY_SUMMARY_ENV: str(summary_path),
        OBSERVABILITY_EVENTS_ENV: str(events_path),
    }


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
) -> dict[str, Any]:
    """Validate a persisted sidecar and its referenced artifacts fail-closed."""

    root_path = (root or summary_path.parent).resolve()
    try:
        raw = summary_path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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

    issues: list[str] = []
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        issues.append("artifacts_missing")
    else:
        for name, item in artifacts.items():
            if not isinstance(item, dict):
                issues.append(f"artifact_not_object:{name}")
                continue
            if name == "summary":
                # The summary digest is a canonical self-digest.  It cannot
                # equal the hash of the rendered file that contains it.
                continue
            path_value = item.get("path")
            recorded = item.get("sha256")
            if not isinstance(path_value, str) or not path_value:
                if name == "result" and recorded is None:
                    continue
                issues.append(f"artifact_path_missing:{name}")
                continue
            path = _resolve_artifact_path(path_value, root_path)
            actual = hash_file(path)
            if actual is None:
                issues.append(f"artifact_missing:{name}")
            elif isinstance(recorded, str) and actual != recorded:
                issues.append(f"artifact_hash_mismatch:{name}")

    events_item = artifacts.get("events") if isinstance(artifacts, dict) else None
    events_path = _resolve_artifact_path(
        str(events_item.get("path")) if isinstance(events_item, dict) else "",
        root_path,
    )
    events = _read_event_log(events_path)
    issues.extend(events["issues"])

    expected_self = None
    if isinstance(artifacts, dict):
        summary_item = artifacts.get("summary")
        if isinstance(summary_item, dict):
            expected_self = summary_item.get("sha256")
    if isinstance(expected_self, str):
        without_self = _summary_digest_payload(payload)
        if sha256_bytes(_json_bytes(without_self)) != expected_self:
            issues.append("artifact_hash_mismatch:summary")

    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        issues.append("provenance_missing")
    else:
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
        summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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
    artifacts = summary_payload.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        summary_payload["artifacts"] = artifacts
    for name in ("stdout", "stderr"):
        item = normalized.get("artifacts", {}).get(name)
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
        self.started_monotonic = time.monotonic()
        self.started_at = _utc_now()
        self.expected_provenance = collect_runner_provenance(argv, env=env)
        self._sequence = 0
        self._event_count = 0
        self._dropped_count = 0
        self._lock = threading.Lock()
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.write_bytes(b"")

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
            "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 6),
            **fields,
        }
        encoded = _json_bytes(record) + b"\n"
        if len(encoded) > MAX_EVENT_LINE_BYTES:
            self._dropped_count += 1
            return
        with self._lock:
            try:
                current_size = self.events_path.stat().st_size
                if (
                    self._event_count >= MAX_EVENT_COUNT
                    or current_size + len(encoded) > MAX_EVENT_LOG_BYTES
                ):
                    self._dropped_count += 1
                    return
                with self.events_path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                self._event_count += 1
            except OSError:
                self._dropped_count += 1

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
    ) -> dict[str, Any]:
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
                "dropped_count": self._dropped_count,
                "bounded": True,
                "max_events": MAX_EVENT_COUNT,
                "max_bytes": MAX_EVENT_LOG_BYTES,
                "issues": sorted(set(issues)),
            },
        }
        self._write_summary(summary)
        return normalize_observability_paths(summary, root=Path.cwd())

    def _next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def _write_summary(self, summary: dict[str, Any]) -> None:
        summary_item = summary.get("artifacts", {}).get("summary")
        if isinstance(summary_item, dict):
            summary_item["sha256"] = None
        summary_bytes = _json_bytes(_summary_digest_payload(summary))
        if isinstance(summary_item, dict):
            summary_item["sha256"] = sha256_bytes(summary_bytes)
        rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary = self.summary_path.with_name(f".{self.summary_path.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, self.summary_path)


class _PytestEventSink:
    def __init__(self, summary_path: Path, events_path: Path) -> None:
        self.summary_path = summary_path
        self.events_path = events_path
        self.started_monotonic = time.monotonic()
        self.sequence = 0
        self.event_count = 0
        self.dropped_count = 0
        self.collection_count: int | None = None
        self.started_count = 0
        self.completed_count = 0

    def emit(self, event: str, *, phase: str, **fields: Any) -> None:
        self.sequence += 1
        encoded = (
            _json_bytes(
                {
                    "contract_version": RUNNER_OBSERVABILITY_CONTRACT_VERSION,
                    "sequence": self.sequence,
                    "event": event,
                    "phase": phase,
                    "source": "pytest_hook",
                    "at": _utc_now(),
                    "elapsed_seconds": round(
                        time.monotonic() - self.started_monotonic, 6
                    ),
                    **fields,
                }
            )
            + b"\n"
        )
        if len(encoded) > MAX_EVENT_LINE_BYTES:
            self.dropped_count += 1
            return
        try:
            if (
                self.event_count >= MAX_EVENT_COUNT
                or self.events_path.stat().st_size + len(encoded) > MAX_EVENT_LOG_BYTES
            ):
                self.dropped_count += 1
                return
            with self.events_path.open("ab") as stream:
                stream.write(encoded)
                stream.flush()
            self.event_count += 1
        except OSError:
            self.dropped_count += 1


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
    return dict(expected) == dict(observed)


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
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
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
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _summary_digest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove self-references before hashing the persisted summary."""

    without_self = json.loads(json.dumps(dict(payload), ensure_ascii=False))
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
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)
    return rendered.encode("utf-8")


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
