from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable
import uuid

from .contracts.runner_execution_receipt import (
    RUNNER_EXECUTION_RECEIPT_CONTRACT_VERSION,
    compute_cross_attempt_binding_sha256,
    finalize_runner_execution_receipt,
    load_runner_execution_receipt,
    serialized_runner_execution_receipt,
    validate_runner_execution_receipt,
)


RUNNER_EXECUTION_FRAME_CONTRACT_VERSION = "runner-execution-frame/v1"
RUNNER_EXECUTION_FRAME_FD_ENV = "PCL_RUNNER_OBSERVABILITY_FRAME_FD"
MAX_RUNNER_FRAME_BYTES = 16_384
MAX_RUNNER_FRAME_COUNT = 16_384
MAX_RUNNER_FRAME_BUFFER_BYTES = MAX_RUNNER_FRAME_BYTES * 2
FRAME_READER_JOIN_SECONDS = 2.0


class RunnerExecutionReceiptError(RuntimeError):
    """Raised when a runner receipt cannot be sealed or verified."""


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def hash_argv(argv: Iterable[str]) -> str:
    return sha256_json([str(item) for item in argv])


def hash_cwd(cwd: Path | str) -> str:
    return sha256_json(str(Path(cwd).resolve()))


def hash_environment(environment: Mapping[str, str]) -> str:
    return sha256_json(sorted((str(name), str(value)) for name, value in environment.items()))


def sha256_json(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def canonical_frame_bytes(frame: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            frame,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def encode_child_frame(observation: Mapping[str, Any]) -> bytes:
    """Encode a child diagnostic observation for the anonymous pipe.

    The wrapper is deliberately a frame contract rather than a receipt. The
    parent assigns its own sequence and root after parsing the frame.
    """

    frame = {
        "contract_version": RUNNER_EXECUTION_FRAME_CONTRACT_VERSION,
        "observation": deepcopy(dict(observation)),
    }
    return canonical_frame_bytes(frame)


def write_child_frame(
    observation: Mapping[str, Any],
    *,
    fd: int | None = None,
) -> bool:
    """Best-effort child emission; a child write never becomes authority."""

    selected_fd = fd
    if selected_fd is None:
        value = os.environ.get(RUNNER_EXECUTION_FRAME_FD_ENV)
        if value is None:
            return False
        try:
            selected_fd = int(value)
        except ValueError:
            return False
    payload = encode_child_frame(observation)
    if len(payload) > MAX_RUNNER_FRAME_BYTES:
        return False
    try:
        view = memoryview(payload)
        while view:
            written = os.write(selected_fd, view)
            if written <= 0:
                return False
            view = view[written:]
    except OSError:
        return False
    return True


class _ParentFrameCollector:
    def __init__(self) -> None:
        self.sequence = 0
        self.dropped_count = 0
        self.frame_root = sha256_bytes(b"")
        self.frames_eof = False
        self.partial_frame = False
        self.reader_error = False
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def feed(self, chunk: bytes) -> None:
        with self._lock:
            self._buffer.extend(chunk)
            if len(self._buffer) > MAX_RUNNER_FRAME_BUFFER_BYTES:
                newline = self._buffer.find(b"\n")
                if newline < 0:
                    self._buffer.clear()
                else:
                    del self._buffer[: newline + 1]
                self.dropped_count += 1
            while b"\n" in self._buffer:
                line, _, remainder = self._buffer.partition(b"\n")
                self._buffer = bytearray(remainder)
                self._accept_line(bytes(line))

    def finish(self) -> None:
        with self._lock:
            if self._buffer:
                self.partial_frame = True
                self.dropped_count += 1
                self._buffer.clear()
            self.frames_eof = True

    def fail(self) -> None:
        with self._lock:
            self.reader_error = True
            self.dropped_count += 1
            self.frames_eof = False

    def _accept_line(self, line: bytes) -> None:
        if not line:
            self.dropped_count += 1
            return
        if len(line) + 1 > MAX_RUNNER_FRAME_BYTES:
            self.dropped_count += 1
            return
        try:
            value = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_json_number,
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self.dropped_count += 1
            return
        if not isinstance(value, dict):
            self.dropped_count += 1
            return
        if value.get("contract_version") != RUNNER_EXECUTION_FRAME_CONTRACT_VERSION:
            self.dropped_count += 1
            return
        if not isinstance(value.get("observation"), dict):
            self.dropped_count += 1
            return
        canonical = canonical_frame_bytes(value)
        if len(canonical) > MAX_RUNNER_FRAME_BYTES:
            self.dropped_count += 1
            return
        self.sequence += 1
        self.frame_root = sha256_bytes(self.frame_root.encode("ascii") + canonical)


class RunnerExecutionReceiptRecorder:
    """Parent-owned observer and one-shot sealer for one process attempt."""

    def __init__(
        self,
        *,
        receipt_path: Path,
        requested_argv: Iterable[str],
        spawned_argv: Iterable[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
        attempt_id: str | None = None,
        attempt_index: int = 0,
        previous_attempt_id: str | None = None,
        previous_receipt_sha256: str | None = None,
        summary_path: Path | None = None,
        events_path: Path | None = None,
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1")
        self.receipt_path = Path(receipt_path)
        self.requested_argv = [str(item) for item in requested_argv]
        self.spawned_argv = [str(item) for item in spawned_argv]
        self.cwd = Path(cwd)
        self.env = {str(name): str(value) for name, value in env.items()}
        self.timeout_seconds = timeout_seconds
        self.attempt_id = attempt_id or f"attempt-{uuid.uuid4().hex}"
        self.attempt_index = attempt_index
        self.previous_attempt_id = previous_attempt_id
        self.previous_receipt_sha256 = previous_receipt_sha256
        self.summary_path = Path(summary_path) if summary_path is not None else None
        self.events_path = Path(events_path) if events_path is not None else None
        self.started_at = _utc_now()
        self._pipe_read_fd: int | None = None
        self._pipe_write_fd: int | None = None
        self._reader: threading.Thread | None = None
        self._parent_write_closed = False
        self._sealed = False
        self._collector = _ParentFrameCollector()

    @property
    def requested_argv_sha256(self) -> str:
        return hash_argv(self.requested_argv)

    @property
    def spawned_argv_sha256(self) -> str:
        return hash_argv(self.spawned_argv)

    @property
    def pipe_pass_fds(self) -> tuple[int, ...]:
        return (self._pipe_write_fd,) if self._pipe_write_fd is not None else ()

    @property
    def anonymous_pipe_available(self) -> bool:
        return self._pipe_write_fd is not None

    def prepare_pipe(self) -> dict[str, str]:
        if self._pipe_write_fd is not None or self._pipe_read_fd is not None:
            raise RunnerExecutionReceiptError("Runner observation pipe was already prepared")
        if os.name != "posix":
            return {}
        try:
            read_fd, write_fd = os.pipe()
            os.set_inheritable(write_fd, True)
        except OSError as exc:
            self._collector.reader_error = True
            self._collector.dropped_count += 1
            raise RunnerExecutionReceiptError("Unable to prepare runner observation pipe") from exc
        self._pipe_read_fd = read_fd
        self._pipe_write_fd = write_fd
        return {RUNNER_EXECUTION_FRAME_FD_ENV: str(write_fd)}

    def start_reader(self) -> None:
        if self._pipe_read_fd is None:
            self._collector.frames_eof = True
            return
        read_fd = self._pipe_read_fd

        def read_frames() -> None:
            try:
                while True:
                    chunk = os.read(read_fd, 65_536)
                    if not chunk:
                        self._collector.finish()
                        return
                    self._collector.feed(chunk)
            except OSError:
                self._collector.fail()
            finally:
                try:
                    os.close(read_fd)
                except OSError:
                    pass

        self._reader = threading.Thread(
            target=read_frames,
            name="pcl-runner-execution-receipt-frames",
            daemon=True,
        )
        self._reader.start()

    def close_parent_write(self) -> None:
        if self._parent_write_closed:
            return
        self._parent_write_closed = True
        if self._pipe_write_fd is None:
            return
        try:
            os.close(self._pipe_write_fd)
        except OSError:
            pass

    def finish_reader(self, *, timeout: float = FRAME_READER_JOIN_SECONDS) -> None:
        self.close_parent_write()
        if self._reader is None:
            self._collector.frames_eof = True
            return
        self._reader.join(timeout=timeout)
        if self._reader.is_alive():
            self._collector.fail()

    def seal(
        self,
        *,
        spawn_status: str,
        spawn_error_kind: str | None,
        pid: int | None,
        pgid: int | None,
        exit_code: int | None,
        timed_out: bool,
        termination: Mapping[str, Any],
        stdout_sha256: str,
        stderr_sha256: str,
        stdout_eof: bool,
        stderr_eof: bool,
    ) -> dict[str, Any]:
        if self._sealed:
            raise RunnerExecutionReceiptError("Runner execution receipt cannot be sealed twice")
        self._sealed = True
        self.finish_reader()

        normalized_spawn_status = (
            spawn_status if spawn_status in {"not_attempted", "spawned", "failed"} else "failed"
        )
        group_state = str(termination.get("group_state") or "not_started")
        if normalized_spawn_status == "spawned" and group_state == "not_started":
            group_state = "unknown"
        normalized_termination = {
            "requested": bool(termination.get("requested")),
            "method": str(termination.get("method") or "process_exit"),
            "escalated": bool(termination.get("escalated")),
            "term_sent": bool(termination.get("term_sent")),
            "kill_sent": bool(termination.get("kill_sent")),
            "group_state": group_state,
            "leader_alive": bool(termination.get("leader_alive")),
            "pipes_eof": bool(stdout_eof and stderr_eof),
        }
        child_observation = self._child_observation()
        platform_capability = _platform_capability(
            anonymous_pipe=self.anonymous_pipe_available,
            group_state=group_state,
        )
        receipt = {
            "contract_version": RUNNER_EXECUTION_RECEIPT_CONTRACT_VERSION,
            "receipt_sha256": "",
            "attempt_id": self.attempt_id,
            "attempt_index": self.attempt_index,
            "previous_attempt_id": self.previous_attempt_id,
            "previous_receipt_sha256": self.previous_receipt_sha256,
            "cross_attempt_binding_sha256": "",
            "requested_argv_sha256": self.requested_argv_sha256,
            "spawned_argv_sha256": (
                self.spawned_argv_sha256 if normalized_spawn_status == "spawned" else None
            ),
            "cwd": str(self.cwd.resolve()),
            "cwd_identity_sha256": hash_cwd(self.cwd),
            "env_identity_sha256": hash_environment(self.env),
            "pid": pid if normalized_spawn_status == "spawned" else None,
            "pgid": pgid if normalized_spawn_status == "spawned" else None,
            "started_at": self.started_at,
            "ended_at": _utc_now(),
            "event_sequence": self._collector.sequence,
            "event_frame_root_sha256": self._collector.frame_root,
            "dropped_count": self._collector.dropped_count,
            "eof": {
                "stdout": bool(stdout_eof),
                "stderr": bool(stderr_eof),
                "frames": bool(self._collector.frames_eof),
            },
            "exit_code": exit_code,
            "timed_out": bool(timed_out),
            "timeout_seconds": self.timeout_seconds,
            "spawn": {
                "status": normalized_spawn_status,
                "error_kind": spawn_error_kind if normalized_spawn_status == "failed" else None,
            },
            "termination": normalized_termination,
            "stdout_sha256": stdout_sha256,
            "stderr_sha256": stderr_sha256,
            "child_observation": child_observation,
            "platform_capability": platform_capability,
        }
        finalized = finalize_runner_execution_receipt(receipt)
        validation = validate_runner_execution_receipt(finalized)
        if not validation.ok:
            raise RunnerExecutionReceiptError(
                "Parent produced an invalid runner execution receipt: "
                + "; ".join(validation.errors)
            )
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.receipt_path.open("x", encoding="utf-8") as stream:
                stream.write(serialized_runner_execution_receipt(finalized))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise RunnerExecutionReceiptError(
                "Runner execution receipt path already exists; resealing is forbidden"
            ) from exc
        return finalized

    def _child_observation(self) -> dict[str, Any]:
        if self._pipe_write_fd is None and os.name != "posix":
            status = "not_applicable"
        elif self._collector.sequence > 0:
            status = "partial" if self._collector.partial_frame or self._collector.dropped_count else "received"
        elif self._collector.partial_frame or self._collector.dropped_count:
            status = "partial"
        else:
            status = "missing"
        summary_sha256 = hash_file(self.summary_path) if self.summary_path is not None else None
        events_sha256 = hash_file(self.events_path) if self.events_path is not None else None
        return {
            "authority": "non_authoritative",
            "status": status,
            "frames_received": self._collector.sequence,
            "summary_sha256": summary_sha256,
            "events_sha256": events_sha256,
        }


def verify_runner_execution_receipt(
    path: str | Path,
    *,
    expected_attempt_id: str | None = None,
    expected_requested_argv_sha256: str | None = None,
    expected_previous_receipt_sha256: str | None = None,
    summary_path: Path | str | None = None,
    events_path: Path | str | None = None,
    result_path: Path | str | None = None,
) -> dict[str, Any]:
    try:
        payload = load_runner_execution_receipt(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "failure_kind": "receipt_invalid",
            "issues": [f"receipt_unreadable:{exc.__class__.__name__}"],
        }
    validation = validate_runner_execution_receipt(payload)
    issues = list(validation.errors)
    if expected_attempt_id is not None and (
        not isinstance(payload, dict) or payload.get("attempt_id") != expected_attempt_id
    ):
        issues.append("attempt_id_mismatch")
    if expected_requested_argv_sha256 is not None and (
        not isinstance(payload, dict)
        or payload.get("requested_argv_sha256") != expected_requested_argv_sha256
    ):
        issues.append("requested_argv_hash_mismatch")
    if expected_previous_receipt_sha256 is not None and (
        not isinstance(payload, dict)
        or payload.get("previous_receipt_sha256") != expected_previous_receipt_sha256
    ):
        issues.append("previous_receipt_hash_mismatch")
    if isinstance(payload, dict):
        child = payload.get("child_observation")
        if isinstance(child, Mapping):
            if summary_path is not None:
                actual_summary = hash_file(summary_path)
                if actual_summary != child.get("summary_sha256"):
                    issues.append("child_summary_hash_mismatch")
            if events_path is not None:
                actual_events = hash_file(events_path)
                if actual_events != child.get("events_sha256"):
                    issues.append("child_events_hash_mismatch")
        if result_path is not None:
            # The receipt-only slice intentionally does not bind finish/result
            # artifacts. A caller must not treat a result sidecar as verified.
            issues.append("result_unbound_by_receipt")
    if issues:
        return {
            "ok": False,
            "failure_kind": "receipt_invalid",
            "issues": sorted(set(issues)),
            "payload": payload,
        }
    return {"ok": True, "failure_kind": None, "issues": [], "payload": payload}


def hash_file(path: Path | str) -> str | None:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(65_536), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return None


def platform_capability(*, anonymous_pipe: bool, group_state: str) -> dict[str, str]:
    return _platform_capability(
        anonymous_pipe=anonymous_pipe,
        group_state=group_state,
    )


def _platform_capability(*, anonymous_pipe: bool, group_state: str) -> dict[str, str]:
    if os.name == "nt":
        return {
            "os": "windows",
            "anonymous_pipe": "not_applicable",
            "process_group": "not_applicable",
            "status": "not_applicable",
        }
    if os.name == "posix":
        return {
            "os": "posix",
            "anonymous_pipe": "available" if anonymous_pipe else "uncertain",
            "process_group": "uncertain",
            "status": "uncertain",
        }
    return {
        "os": "other",
        "anonymous_pipe": "available" if anonymous_pipe else "uncertain",
        "process_group": "uncertain" if group_state == "unknown" else "available",
        "status": "uncertain",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


# Explicit aliases make the parent/child boundary readable to callers that use
# either the observer or recorder vocabulary.
ParentRunnerExecutionReceipt = RunnerExecutionReceiptRecorder
RunnerExecutionReceiptObserver = RunnerExecutionReceiptRecorder
verify_runner_receipt = verify_runner_execution_receipt
compute_runner_cross_attempt_binding_sha256 = compute_cross_attempt_binding_sha256
