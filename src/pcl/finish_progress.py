from __future__ import annotations

from collections.abc import Callable
import json
import threading
import time
from typing import Any, TextIO


FINISH_PROGRESS_CONTRACT_VERSION = "finish-progress/v1"
FINISH_PROGRESS_DELIVERY_CONTRACT_VERSION = "finish-progress-delivery/v1"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0

ProgressCallback = Callable[[dict[str, Any]], None]
Clock = Callable[[], float]
HeartbeatWorkerFactory = Callable[["FinishCheckHeartbeat"], threading.Thread | None]


class FinishProgressSink:
    """Best-effort progress presentation that never changes finish semantics."""

    def __init__(self, output_format: str, *, output: TextIO) -> None:
        if output_format not in {"text", "jsonl"}:
            raise ValueError("output_format must be text or jsonl")
        self.output_format = output_format
        self.output = output
        self.emitted_count = 0
        self.dropped_count = 0
        self._lock = threading.Lock()

    def emit(self, record: dict[str, Any]) -> None:
        rendered = (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if self.output_format == "jsonl"
            else _format_text_record(record)
        )
        try:
            with self._lock:
                self.output.write(rendered + "\n")
                self.output.flush()
                self.emitted_count += 1
        except (OSError, ValueError):
            self.dropped_count += 1

    def summary(self) -> dict[str, Any]:
        return {
            "contract_version": FINISH_PROGRESS_DELIVERY_CONTRACT_VERSION,
            "format": self.output_format,
            "status": "degraded" if self.dropped_count else "complete",
            "emitted_count": self.emitted_count,
            "dropped_count": self.dropped_count,
        }


class FinishProgressReporter:
    """Emit ordered target-bound finish progress through an optional callback."""

    def __init__(
        self,
        callback: ProgressCallback,
        *,
        target_binding: dict[str, str],
        clock: Clock = time.monotonic,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        heartbeat_worker_factory: HeartbeatWorkerFactory | None = None,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be greater than 0")
        self.callback = callback
        self.target_binding = dict(target_binding)
        self.clock = clock
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.heartbeat_worker_factory = (
            heartbeat_worker_factory or _start_heartbeat_worker
        )
        self.started_at = clock()
        self._sequence = 0
        self._lock = threading.Lock()
        self._finished = False

    def emit(
        self,
        *,
        event: str,
        phase: str,
        status: str,
        check: dict[str, Any] | None = None,
        outcome: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        with self._lock:
            if self._finished:
                return
            self._sequence += 1
            record: dict[str, Any] = {
                "contract_version": FINISH_PROGRESS_CONTRACT_VERSION,
                "sequence": self._sequence,
                "event": event,
                "phase": phase,
                "status": status,
                "target_binding": dict(self.target_binding),
                "elapsed_seconds": round(
                    max(0.0, self.clock() - self.started_at),
                    3,
                ),
            }
            if check is not None:
                record["check"] = dict(check)
            if outcome is not None:
                record["outcome"] = outcome
            if exit_code is not None:
                record["exit_code"] = exit_code
            try:
                self.callback(record)
            except Exception:
                pass

    def phase_started(self, phase: str) -> None:
        self.emit(event="phase_started", phase=phase, status="running")

    def phase_finished(self, phase: str) -> None:
        self.emit(event="phase_finished", phase=phase, status="completed")

    def start_check(
        self,
        *,
        index: int,
        count: int,
        config_key: str,
    ) -> FinishCheckHeartbeat:
        check = {
            "index": index,
            "count": count,
            "config_key": config_key,
        }
        self.emit(
            event="check_started",
            phase="checks",
            status="running",
            check=check,
        )
        heartbeat = FinishCheckHeartbeat(
            self,
            check=check,
            interval_seconds=self.heartbeat_interval_seconds,
        )
        heartbeat.worker = self.heartbeat_worker_factory(heartbeat)
        return heartbeat

    def finish_check(
        self,
        heartbeat: FinishCheckHeartbeat,
        *,
        status: str,
        exit_code: int | None,
    ) -> None:
        heartbeat.stop()
        self.emit(
            event="check_finished",
            phase="checks",
            status=status,
            check=heartbeat.check,
            exit_code=exit_code,
        )

    def finish(
        self,
        *,
        status: str,
        outcome: str | None,
        exit_code: int,
    ) -> None:
        self.emit(
            event="finish_finished",
            phase="evidence_commit",
            status=status,
            outcome=outcome,
            exit_code=exit_code,
        )
        self._finished = True


class FinishCheckHeartbeat:
    def __init__(
        self,
        reporter: FinishProgressReporter,
        *,
        check: dict[str, Any],
        interval_seconds: float,
    ) -> None:
        self.reporter = reporter
        self.check = dict(check)
        self.interval_seconds = interval_seconds
        self.last_emitted_at = reporter.clock()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

    def run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            self.tick()

    def tick(self) -> bool:
        current = self.reporter.clock()
        if current - self.last_emitted_at < self.interval_seconds:
            return False
        self.last_emitted_at = current
        self.reporter.emit(
            event="check_heartbeat",
            phase="checks",
            status="running",
            check=self.check,
        )
        return True

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker is not None and self.worker is not threading.current_thread():
            self.worker.join(timeout=1)


def _start_heartbeat_worker(
    heartbeat: FinishCheckHeartbeat,
) -> threading.Thread:
    worker = threading.Thread(
        target=heartbeat.run,
        name="pcl-finish-heartbeat",
        daemon=True,
    )
    worker.start()
    return worker


def _format_text_record(record: dict[str, Any]) -> str:
    parts = [
        "[pcl finish]",
        f"seq={record['sequence']}",
        f"phase={record['phase']}",
        f"event={record['event']}",
        f"status={record['status']}",
        f"elapsed={record['elapsed_seconds']:.3f}s",
    ]
    check = record.get("check")
    if isinstance(check, dict):
        parts.extend(
            [
                f"check={check.get('index')}/{check.get('count')}",
                f"config_key={check.get('config_key')}",
            ]
        )
    if record.get("outcome") is not None:
        parts.append(f"outcome={record['outcome']}")
    return " ".join(parts)
