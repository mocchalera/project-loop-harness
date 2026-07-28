from __future__ import annotations

import importlib
import io
import json


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for item in value.values()
            for key in _nested_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _nested_keys(item)}
    return set()


def test_finish_progress_reporter_emits_bounded_sanitized_heartbeat() -> None:
    finish_progress = importlib.import_module("pcl.finish_progress")
    now = [0.0]
    records: list[dict] = []
    reporter = finish_progress.FinishProgressReporter(
        records.append,
        target_binding={
            "target_type": "task",
            "target_id": "T-0001",
            "source": "explicit",
        },
        clock=lambda: now[0],
        heartbeat_interval_seconds=30.0,
        heartbeat_worker_factory=lambda heartbeat: None,
    )

    reporter.emit(
        event="finish_started",
        phase="planning",
        status="completed",
    )
    heartbeat = reporter.start_check(
        index=1,
        count=2,
        config_key="project.commands.test",
    )
    now[0] = 29.0
    assert heartbeat.tick() is False
    now[0] = 30.0
    assert heartbeat.tick() is True
    assert heartbeat.tick() is False
    now[0] = 60.0
    assert heartbeat.tick() is True
    reporter.finish_check(
        heartbeat,
        status="timed_out",
        exit_code=None,
    )
    reporter.finish(
        status="incomplete",
        outcome="INCOMPLETE_VALIDATION",
        exit_code=1,
    )

    assert [record["sequence"] for record in records] == [1, 2, 3, 4, 5, 6]
    heartbeats = [
        record for record in records if record["event"] == "check_heartbeat"
    ]
    assert [record["elapsed_seconds"] for record in heartbeats] == [30.0, 60.0]
    assert records[-2]["status"] == "timed_out"
    assert records[-1]["status"] == "incomplete"
    progress_keys = _nested_keys(records)
    for forbidden in ("argv", "command", "stdout", "stderr", "environment"):
        assert forbidden not in progress_keys


def test_finish_progress_sink_formats_jsonl_and_degrades_without_raising() -> None:
    finish_progress = importlib.import_module("pcl.finish_progress")
    output = io.StringIO()
    sink = finish_progress.FinishProgressSink("jsonl", output=output)
    record = {
        "contract_version": "finish-progress/v1",
        "sequence": 1,
        "event": "finish_started",
        "phase": "planning",
        "status": "completed",
        "target_binding": {
            "target_type": "task",
            "target_id": "T-0001",
            "source": "explicit",
        },
        "elapsed_seconds": 0.0,
    }

    sink.emit(record)
    assert json.loads(output.getvalue()) == record
    assert sink.summary() == {
        "contract_version": "finish-progress-delivery/v1",
        "format": "jsonl",
        "status": "complete",
        "emitted_count": 1,
        "dropped_count": 0,
    }

    class BrokenOutput:
        def write(self, value: str) -> int:
            raise OSError("closed")

        def flush(self) -> None:
            raise OSError("closed")

    degraded = finish_progress.FinishProgressSink("text", output=BrokenOutput())
    degraded.emit(record)
    assert degraded.summary() == {
        "contract_version": "finish-progress-delivery/v1",
        "format": "text",
        "status": "degraded",
        "emitted_count": 0,
        "dropped_count": 1,
    }
