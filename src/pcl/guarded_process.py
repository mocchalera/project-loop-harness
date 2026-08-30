from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Pattern

from .errors import InvalidInputError
from .redaction import redact_bytes
from .runner_observability import (
    RunnerObservabilityRecorder,
    inject_pytest_hook,
    observability_environment,
)
from .runner_execution_receipt import RunnerExecutionReceiptRecorder


DEFAULT_MAX_OUTPUT_BYTES = 1_048_576
READ_CHUNK_BYTES = 65_536
DEFAULT_ENV_ALLOWLIST = frozenset(
    {
        "CI",
        "CI_NODE_INDEX",
        "CI_NODE_TOTAL",
        "COLORTERM",
        "COMSPEC",
        "FORCE_COLOR",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
        "PATH",
        "PATHEXT",
        "PYTHONPATH",
        "PYTHONHASHSEED",
        "PYTEST_RANDOMLY_SEED",
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "RANDOM_SEED",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TEST_SHARD_INDEX",
        "TEST_TOTAL_SHARDS",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "VIRTUAL_ENV",
    }
)


class _BoundedStream:
    def __init__(self, max_bytes: int, *, tail_bytes: int = 0) -> None:
        self.max_bytes = max_bytes
        self.tail_bytes = tail_bytes
        self.captured_byte_count = 0
        self.original_byte_count = 0
        self.eof = False
        self.file = tempfile.TemporaryFile(mode="w+b")
        self.tail_buffer = bytearray()

    def consume(self, chunk: bytes) -> None:
        self.original_byte_count += len(chunk)
        remaining = self.max_bytes - self.captured_byte_count
        if remaining > 0:
            retained = chunk[:remaining]
            self.file.write(retained)
            self.captured_byte_count += len(retained)
        if self.tail_bytes > 0:
            if len(chunk) >= self.tail_bytes:
                self.tail_buffer = bytearray(chunk[-self.tail_bytes :])
            else:
                self.tail_buffer.extend(chunk)
                overflow = len(self.tail_buffer) - self.tail_bytes
                if overflow > 0:
                    del self.tail_buffer[:overflow]

    def read(self) -> bytes:
        self.file.flush()
        self.file.seek(0)
        return self.file.read()

    def read_tail(self) -> bytes:
        return bytes(self.tail_buffer)

    def close(self) -> None:
        self.file.close()


def build_subprocess_env(
    *,
    additional_allowed_names: Iterable[str] = (),
) -> tuple[dict[str, str], dict[str, Any]]:
    additional = frozenset(additional_allowed_names)
    invalid = sorted(name for name in additional if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))
    if invalid:
        raise InvalidInputError(
            "Executor environment allowlist contains an invalid variable name.",
            details={"invalid_names": invalid},
        )
    allowed = DEFAULT_ENV_ALLOWLIST | additional
    inherited = {name: value for name, value in os.environ.items() if name in allowed}
    current_src = str(Path(__file__).resolve().parents[1])
    entries: list[str] = []
    for raw_entry in inherited.get("PYTHONPATH", "").split(os.pathsep):
        if not raw_entry:
            continue
        entry_path = Path(raw_entry)
        if not entry_path.is_absolute():
            entry_path = (Path.cwd() / entry_path).resolve()
        resolved = str(entry_path)
        if resolved != current_src:
            entries.append(resolved)
    inherited["PYTHONPATH"] = os.pathsep.join([current_src, *entries])
    inherited_names = sorted(inherited)
    return inherited, {
        "inheritance": "allowlist",
        "inherited_names": inherited_names,
        "blocked_name_count": len(set(os.environ) - set(inherited_names)),
        "sha256": _environment_sha256(inherited),
        "execution_context": {
            "worker_sha256": _selected_environment_sha256(
                inherited,
                {"PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT"},
            ),
            "shard_sha256": _selected_environment_sha256(
                inherited,
                {
                    "CI_NODE_INDEX",
                    "CI_NODE_TOTAL",
                    "TEST_SHARD_INDEX",
                    "TEST_TOTAL_SHARDS",
                },
            ),
            "seed_sha256": _selected_environment_sha256(
                inherited,
                {"PYTHONHASHSEED", "PYTEST_RANDOMLY_SEED", "RANDOM_SEED"},
            ),
        },
        "values_recorded": False,
    }


def execute_guarded_process(
    argv: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    tail_output_bytes: int = 0,
    stdout_tail_path: Path | None = None,
    stderr_tail_path: Path | None = None,
    redaction_patterns: Iterable[Pattern[str]] = (),
    additional_allowed_env_names: Iterable[str] = (),
    observability_summary_path: Path | None = None,
    observability_events_path: Path | None = None,
    runner_execution_receipt_path: Path | None = None,
    execution_receipt_path: Path | None = None,
    attempt_id: str | None = None,
    attempt_index: int = 0,
    previous_attempt_id: str | None = None,
    previous_receipt_sha256: str | None = None,
    execution_instance_id: str | None = None,
    runner_sidecar_policy: str | dict[str, Any] | None = None,
    defer_runner_authority_seal: bool = False,
) -> dict[str, Any]:
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be at least 1")
    if tail_output_bytes < 0:
        raise ValueError("tail_output_bytes cannot be negative")
    patterns = tuple(redaction_patterns)
    env, environment_contract = build_subprocess_env(
        additional_allowed_names=additional_allowed_env_names
    )
    if (observability_summary_path is None) != (observability_events_path is None):
        raise ValueError(
            "observability_summary_path and observability_events_path must be provided together"
        )
    if (
        runner_execution_receipt_path is not None
        and execution_receipt_path is not None
        and Path(runner_execution_receipt_path) != Path(execution_receipt_path)
    ):
        raise ValueError(
            "runner_execution_receipt_path and execution_receipt_path must match when both are provided"
        )
    receipt_path = runner_execution_receipt_path or execution_receipt_path
    if receipt_path is None and observability_summary_path is not None:
        receipt_path = Path(observability_summary_path).with_name(
            "runner-execution-receipt.json"
        )
    observed_argv = list(argv)
    observability: RunnerObservabilityRecorder | None = None
    receipt_observer: RunnerExecutionReceiptRecorder | None = None
    if (
        observability_summary_path is not None
        and observability_events_path is not None
    ) or receipt_path is not None:
        observed_argv, _ = inject_pytest_hook(observed_argv)
    if observability_summary_path is not None and observability_events_path is not None:
        observability = RunnerObservabilityRecorder(
            summary_path=observability_summary_path,
            events_path=observability_events_path,
            argv=observed_argv,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        observability.start()
        env.update(observability_environment(observability_summary_path, observability_events_path))
    if receipt_path is not None:
        receipt_observer = RunnerExecutionReceiptRecorder(
            receipt_path=Path(receipt_path),
            requested_argv=argv,
            spawned_argv=observed_argv,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            previous_attempt_id=previous_attempt_id,
            previous_receipt_sha256=previous_receipt_sha256,
            summary_path=observability_summary_path,
            events_path=observability_events_path,
            execution_instance_id=execution_instance_id,
            sidecar_policy=runner_sidecar_policy,
            observation_callback=(
                observability.observe_child_observation
                if observability is not None
                else None
            ),
        )
        env.update(receipt_observer.prepare_pipe())
        if observability is not None:
            observability.set_parent_observation_channel(
                receipt_observer.anonymous_pipe_available
            )
        receipt_observer.start_reader()
    stdout_capture = _BoundedStream(max_output_bytes, tail_bytes=tail_output_bytes)
    stderr_capture = _BoundedStream(max_output_bytes, tail_bytes=tail_output_bytes)
    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    spawn_error = ""
    spawn_error_kind = ""
    termination = {"requested": False, "method": "", "escalated": False}
    heartbeat_stop: threading.Event | None = None
    heartbeat_worker: threading.Thread | None = None
    process: subprocess.Popen[bytes] | None = None
    process_group_id: int | None = None

    try:
        popen_kwargs: dict[str, Any] = {
            "cwd": cwd,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "text": False,
            "start_new_session": True,
        }
        if receipt_observer is not None and receipt_observer.pipe_pass_fds:
            popen_kwargs["pass_fds"] = receipt_observer.pipe_pass_fds
        process = subprocess.Popen(observed_argv, **popen_kwargs)
        if os.name == "posix":
            try:
                process_group_id = os.getpgid(process.pid)
            except OSError:
                process_group_id = None
        if receipt_observer is not None:
            receipt_observer.close_parent_write()
    except OSError as exc:
        spawn_error = f"{exc.__class__.__name__}: {exc}\n"
        spawn_error_kind = (
            "not_found"
            if isinstance(exc, FileNotFoundError)
            else "permission_denied"
            if isinstance(exc, PermissionError)
            else "os_error"
        )
        stderr_capture.consume(spawn_error.encode("utf-8", errors="replace"))
        stdout_capture.eof = True
        stderr_capture.eof = True
        if receipt_observer is not None:
            receipt_observer.close_parent_write()
    else:
        assert process.stdout is not None
        assert process.stderr is not None
        if observability is not None:
            heartbeat_stop, heartbeat_worker = observability.start_heartbeat(process)
        threads = [
            threading.Thread(target=_drain_stream, args=(process.stdout, stdout_capture), daemon=True),
            threading.Thread(target=_drain_stream, args=(process.stderr, stderr_capture), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination = _terminate_process_group(process)
            exit_code = None
        finally:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_worker is not None:
                heartbeat_worker.join(timeout=1)
            for thread in threads:
                thread.join(timeout=2)
            process.stdout.close()
            process.stderr.close()

    if timed_out and stderr_capture.original_byte_count == 0:
        stderr_capture.consume(f"Timed out after {timeout_seconds} seconds.\n".encode())
    stdout_metadata = _write_capture(
        stdout_capture,
        stdout_path,
        tail_path=stdout_tail_path,
        redaction_patterns=patterns,
    )
    stderr_metadata = _write_capture(
        stderr_capture,
        stderr_path,
        tail_path=stderr_tail_path,
        redaction_patterns=patterns,
    )
    if process is not None:
        termination = {
            **termination,
            **_final_process_group_state(process.pid, leader_alive=process.poll() is None),
            "pipes_eof": stdout_capture.eof and stderr_capture.eof,
        }
    else:
        termination["group_state"] = "not_started"
        termination["pipes_eof"] = stdout_capture.eof and stderr_capture.eof
    if receipt_observer is not None:
        receipt_observer.finish_reader()
    result: dict[str, Any] = {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 6),
        "failure_kind": "spawn_error" if spawn_error else ("timeout" if timed_out else ""),
        "spawn_error_kind": spawn_error_kind,
        "stdout": stdout_metadata,
        "stderr": stderr_metadata,
        "artifact_collection": {
            "status": "collected",
            "stdout": True,
            "stderr": True,
        },
        "output_truncated": stdout_metadata["truncated"] or stderr_metadata["truncated"],
        "redacted": stdout_metadata["redacted"] or stderr_metadata["redacted"],
        "termination": termination,
        "permission_contract": {
            "backend": "host_subprocess",
            "argv": list(observed_argv),
            "shell": False,
            "working_directory": str(cwd),
            "environment": environment_contract,
            "isolation": {
                "os": False,
                "network": False,
                "filesystem": False,
            },
        },
        "executed_argv": list(observed_argv),
    }
    if observability is not None:
        observability.emit(
            "termination",
            phase="terminate" if timed_out else "complete",
            source="watchdog",
            reason=("timeout_budget_exhausted" if timed_out else "process_exit"),
            termination=termination,
        )
        result["observability"] = observability.finalize(
            stdout=stdout_metadata,
            stderr=stderr_metadata,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_seconds=result["duration_seconds"],
            termination=termination,
            pipes_eof=bool(termination.get("pipes_eof")),
            parent_observation_integrity=(
                receipt_observer.observation_integrity()
                if receipt_observer is not None
                else None
            ),
        )
    if receipt_observer is not None:
        seal_inputs = {
            "spawn_status": "spawned" if process is not None else "failed",
            "spawn_error_kind": spawn_error_kind or None,
            "pid": process.pid if process is not None else None,
            "pgid": process_group_id,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "termination": termination,
            "stdout_sha256": str(stdout_metadata["sha256"]),
            "stderr_sha256": str(stderr_metadata["sha256"]),
            "stdout_eof": bool(stdout_capture.eof),
            "stderr_eof": bool(stderr_capture.eof),
        }
        if defer_runner_authority_seal:
            result["_runner_execution_receipt_recorder"] = receipt_observer
            result["_runner_execution_seal_inputs"] = seal_inputs
            result["_runner_authority_snapshot"] = receipt_observer.authority_snapshot.to_dict()
            return result
        receipt = receipt_observer.seal(
            **seal_inputs,
        )
        result["runner_execution_receipt"] = receipt
        result["runner_execution_receipt_path"] = str(receipt_observer.receipt_path)
        if receipt_observer.authority_seal_draft is not None:
            result["runner_authority_snapshot"] = receipt_observer.authority_snapshot.to_dict()
            result["runner_authority_draft"] = receipt_observer.authority_seal_draft.to_dict()
    return result


def _environment_sha256(environment: dict[str, str]) -> str:
    encoded = json.dumps(
        sorted(environment.items()),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _selected_environment_sha256(
    environment: dict[str, str],
    names: set[str],
) -> str | None:
    selected = sorted(
        (name, environment[name])
        for name in names
        if name in environment
    )
    return _environment_sha256(dict(selected)) if selected else None


def _drain_stream(stream: Any, capture: _BoundedStream) -> None:
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        if not chunk:
            capture.eof = True
            return
        capture.consume(chunk)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    leader_alive = process.poll() is None
    result = {
        "requested": True,
        "method": "terminate_process_group",
        "escalated": False,
        "term_sent": False,
        "kill_sent": False,
        "group_state_before": _process_group_state(
            process.pid,
            leader_alive=leader_alive,
        ),
    }
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
            result["term_sent"] = True
        else:
            process.terminate()
            result["term_sent"] = True
        process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    if _process_group_state(
        process.pid,
        leader_alive=process.poll() is None,
    ) in {"alive", "surviving", "unknown"}:
        result["escalated"] = True
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            result["kill_sent"] = True
            process.wait(timeout=1)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
    result.update(_final_process_group_state(process.pid, leader_alive=process.poll() is None))
    return result


def _process_group_state(pid: int, *, leader_alive: bool | None = None) -> str:
    if os.name != "posix":
        if leader_alive is False:
            return "not_applicable"
        return "unknown"
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        return "unknown"
    except OSError:
        return "unknown"
    return "alive"


def _final_process_group_state(pid: int, *, leader_alive: bool) -> dict[str, Any]:
    state = _process_group_state(pid, leader_alive=leader_alive)
    return {
        "group_state": "surviving" if state == "alive" else state,
        "group_uncertain": state == "unknown",
        "leader_alive": leader_alive,
    }


def _write_capture(
    capture: _BoundedStream,
    path: Path,
    *,
    tail_path: Path | None,
    redaction_patterns: tuple[Pattern[str], ...],
) -> dict[str, Any]:
    try:
        captured = capture.read()
        tail_captured = capture.read_tail()
        redacted, changed = redact_bytes(captured, additional_patterns=redaction_patterns)
        tail_redacted, tail_changed = redact_bytes(
            tail_captured, additional_patterns=redaction_patterns
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redacted)
        if tail_path is not None and capture.tail_bytes > 0:
            tail_path.parent.mkdir(parents=True, exist_ok=True)
            tail_path.write_bytes(tail_redacted)
    finally:
        capture.close()
    encoding, binary = _encoding_metadata(redacted)
    truncated = capture.original_byte_count > len(captured)
    metadata: dict[str, Any] = {
        "path": str(path),
        "original_byte_count": capture.original_byte_count,
        "captured_byte_count": len(captured),
        "artifact_byte_count": len(redacted),
        "max_bytes": capture.max_bytes,
        "truncated": truncated,
        "truncation_reason": "max_output_bytes_exceeded" if truncated else "",
        "capture_strategy": "head",
        "capture_mode": "streaming_temporary_file",
        "redacted": changed or tail_changed,
        "raw_output_persisted": False,
        "encoding": encoding,
        "binary": binary,
        "sha256": f"sha256:{hashlib.sha256(redacted).hexdigest()}",
    }
    if capture.tail_bytes > 0:
        tail_encoding, tail_binary = _encoding_metadata(tail_redacted)
        metadata["tail"] = {
            "path": str(tail_path) if tail_path is not None else None,
            "captured_byte_count": len(tail_captured),
            "artifact_byte_count": len(tail_redacted) if tail_path is not None else 0,
            "max_bytes": capture.tail_bytes,
            "capture_strategy": "tail",
            "persisted": tail_path is not None,
            "redacted": tail_changed,
            "raw_output_persisted": False,
            "encoding": tail_encoding,
            "binary": tail_binary,
            "sha256": f"sha256:{hashlib.sha256(tail_redacted).hexdigest()}",
        }
    return metadata


def _encoding_metadata(data: bytes) -> tuple[str | None, bool]:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None, True
    return "utf-8", False
