from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from pcl.guarded_process import (
    _final_process_group_state,
    _process_group_state,
    execute_guarded_process,
)
from pcl.runner_observability import (
    RunnerObservabilityRecorder,
    hash_file,
    verify_runner_observability,
)
from pcl.verification_results import build_finish_check_result


def _execute_pytest(tmp_path: Path, *, test_source: str, timeout_seconds: int = 5) -> dict:
    (tmp_path / "test_sample.py").write_text(test_source, encoding="utf-8")
    return execute_guarded_process(
        [sys.executable, "-m", "pytest", "-q", "test_sample.py"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.txt",
        stderr_path=tmp_path / "stderr.txt",
        timeout_seconds=timeout_seconds,
        observability_summary_path=tmp_path / "runner-observability.json",
        observability_events_path=tmp_path / "runner-observability.jsonl",
    )


def test_success_persists_pytest_node_progress_hashes_and_provenance(tmp_path: Path) -> None:
    result = _execute_pytest(tmp_path, test_source="def test_sample():\n    assert True\n")

    observation = result["observability"]
    assert result["exit_code"] == 0
    assert observation["eligible"] is True
    assert observation["source"] == "pytest_hook"
    assert observation["last_started"]["nodeid"] == "test_sample.py::test_sample"
    assert observation["last_completed"]["nodeid"] == "test_sample.py::test_sample"
    assert observation["collection"]["collected_count"] == 1
    assert observation["heartbeat"]["count"] >= 1
    assert observation["provenance"]["status"] == "matched"
    assert observation["artifacts"]["stdout"]["sha256"] == hash_file(tmp_path / "stdout.txt")
    assert verify_runner_observability(
        tmp_path / "runner-observability.json",
        root=tmp_path,
        allow_pending_result=True,
    )["ok"] is True


def test_timeout_persists_last_node_budget_and_termination(tmp_path: Path) -> None:
    result = _execute_pytest(
        tmp_path,
        test_source="import time\n\ndef test_slow():\n    time.sleep(30)\n",
        timeout_seconds=1,
    )

    observation = result["observability"]
    assert result["timed_out"] is True
    assert result["exit_code"] is None
    assert observation["eligible"] is False
    assert observation["failure_kind"] == "timeout_budget_exhausted"
    assert observation["budget"]["exhausted"] is True
    assert observation["budget"]["overshoot_seconds"] >= 0
    assert observation["last_started"]["nodeid"] == "test_sample.py::test_slow"
    assert observation["process_group"]["term_sent"] is True
    assert observation["process_group"]["pipes_eof"] is True


def test_hook_not_loaded_stays_unavailable_even_when_pytest_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pcl.guarded_process.inject_pytest_hook", lambda argv: (argv, False))

    result = _execute_pytest(tmp_path, test_source="def test_sample():\n    assert True\n")

    observation = result["observability"]
    assert result["exit_code"] == 0
    assert observation["eligible"] is False
    assert observation["status"] == "unavailable"
    assert observation["failure_kind"] == "observer_unavailable"


def test_missing_nodeid_is_partial_and_not_eligible(tmp_path: Path) -> None:
    summary_path = tmp_path / "runner-observability.json"
    events_path = tmp_path / "runner-observability.jsonl"
    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_bytes(b"")
    stderr_path.write_bytes(b"")
    recorder = RunnerObservabilityRecorder(
        summary_path=summary_path,
        events_path=events_path,
        argv=["pytest", "test_sample.py"],
        timeout_seconds=5,
        env={"PYTHONPATH": "src"},
    )
    recorder.start()
    recorder.emit(
        "hook_loaded",
        phase="configure",
        source="pytest_hook",
        provenance=recorder.expected_provenance,
    )
    recorder.emit(
        "collection_finished",
        phase="collection",
        source="pytest_hook",
        collected_count=1,
        collection_finished=True,
    )

    observation = recorder.finalize(
        stdout={"path": str(stdout_path), "sha256": hash_file(stdout_path)},
        stderr={"path": str(stderr_path), "sha256": hash_file(stderr_path)},
        exit_code=0,
        timed_out=False,
        duration_seconds=0.1,
        termination={"group_state": "gone", "pipes_eof": True},
        pipes_eof=True,
    )

    assert observation["eligible"] is False
    assert observation["failure_kind"] == "observer_unavailable"
    assert observation["last_started"]["nodeid"] is None


def test_term_with_surviving_group_is_process_group_uncertain(tmp_path: Path) -> None:
    summary_path = tmp_path / "runner-observability.json"
    events_path = tmp_path / "runner-observability.jsonl"
    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_bytes(b"")
    stderr_path.write_bytes(b"")
    recorder = RunnerObservabilityRecorder(
        summary_path=summary_path,
        events_path=events_path,
        argv=[sys.executable, "-c", "pass"],
        timeout_seconds=5,
        env={"PYTHONPATH": "src"},
    )
    recorder.start()

    observation = recorder.finalize(
        stdout={"path": str(stdout_path), "sha256": hash_file(stdout_path)},
        stderr={"path": str(stderr_path), "sha256": hash_file(stderr_path)},
        exit_code=0,
        timed_out=False,
        duration_seconds=0.1,
        termination={
            "requested": True,
            "method": "terminate_process_group",
            "term_sent": True,
            "kill_sent": False,
            "group_state": "surviving",
            "pipes_eof": True,
        },
        pipes_eof=True,
    )

    assert observation["eligible"] is False
    assert observation["failure_kind"] == "process_group_uncertain"
    assert observation["process_group"]["state"] == "surviving"


def test_windows_exited_process_group_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pcl.guarded_process.os.name", "nt")

    state = _final_process_group_state(123, leader_alive=False)
    assert _process_group_state(123) == "unknown"
    assert state == {
        "group_state": "not_applicable",
        "group_uncertain": False,
        "leader_alive": False,
    }
    monkeypatch.undo()

    recorder = RunnerObservabilityRecorder(
        summary_path=tmp_path / "runner-observability.json",
        events_path=tmp_path / "runner-observability.jsonl",
        argv=[sys.executable, "-c", "pass"],
        timeout_seconds=5,
        env={"PYTHONPATH": "src"},
    )
    recorder.start()
    observation = recorder.finalize(
        stdout={"path": None, "sha256": None},
        stderr={"path": None, "sha256": None},
        exit_code=0,
        timed_out=False,
        duration_seconds=0.1,
        termination={"group_state": "not_applicable", "pipes_eof": True},
        pipes_eof=True,
    )
    assert observation["eligible"] is True


def test_windows_live_process_group_is_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pcl.guarded_process.os.name", "nt")

    state = _final_process_group_state(123, leader_alive=True)
    assert state == {
        "group_state": "unknown",
        "group_uncertain": True,
        "leader_alive": True,
    }
    monkeypatch.undo()

    recorder = RunnerObservabilityRecorder(
        summary_path=tmp_path / "runner-observability.json",
        events_path=tmp_path / "runner-observability.jsonl",
        argv=[sys.executable, "-c", "pass"],
        timeout_seconds=5,
        env={"PYTHONPATH": "src"},
    )
    recorder.start()
    observation = recorder.finalize(
        stdout={"path": None, "sha256": None},
        stderr={"path": None, "sha256": None},
        exit_code=0,
        timed_out=False,
        duration_seconds=0.1,
        termination={"group_state": "unknown", "pipes_eof": True},
        pipes_eof=True,
    )
    assert observation["eligible"] is False
    assert observation["failure_kind"] == "process_group_uncertain"


@pytest.mark.parametrize(
    "failure_kind",
    ["artifact_integrity_failed", "provenance_mismatch", "process_group_uncertain"],
)
def test_observability_failure_never_becomes_passed(failure_kind: str) -> None:
    command = {
        "resolved_command": "python -m pytest",
        "exit_code": 0,
        "timed_out": False,
        "failure_kind": "",
        "spawn_error_kind": "",
        "artifact_collection": {"status": "collected", "stdout": True, "stderr": True},
        "observability": {"eligible": False, "failure_kind": failure_kind, "status": "partial"},
    }

    result = build_finish_check_result(
        command,
        evidence_id="E-0001",
        attempt_identity={"identity_sha256": "sha256:" + "1" * 64},
        stability_evaluation={},
    )

    assert result["status"] == "failed"
    assert result["assertion_result"]["status"] == "unknown"
    assert result["failure_kind"] == failure_kind


def test_empty_observability_failure_kind_still_fails_closed() -> None:
    result = build_finish_check_result(
        {
            "resolved_command": "python -m pytest",
            "exit_code": 0,
            "timed_out": False,
            "failure_kind": "",
            "spawn_error_kind": "",
            "artifact_collection": {
                "status": "collected",
                "stdout": True,
                "stderr": True,
            },
            "observability": {
                "eligible": False,
                "failure_kind": "",
                "status": "unavailable",
            },
        },
        evidence_id="E-0001",
        attempt_identity={"identity_sha256": "sha256:" + "1" * 64},
        stability_evaluation={},
    )

    assert result["status"] == "failed"
    assert result["assertion_result"]["status"] == "unknown"
    assert result["failure_kind"] == "observer_unavailable"


def test_sidecar_corruption_hash_and_provenance_mismatch_fail_closed(tmp_path: Path) -> None:
    _execute_pytest(tmp_path, test_source="def test_sample():\n    assert True\n")
    summary_path = tmp_path / "runner-observability.json"
    events_path = tmp_path / "runner-observability.jsonl"
    stdout_path = tmp_path / "stdout.txt"

    stdout_path.write_text("tampered\n", encoding="utf-8")
    hash_mismatch = verify_runner_observability(summary_path, root=tmp_path)
    assert hash_mismatch["failure_kind"] == "artifact_integrity_failed"
    assert "artifact_hash_mismatch:stdout" in hash_mismatch["issues"]

    events_path.write_bytes(b"{not-json}\n")
    corruption = verify_runner_observability(summary_path, root=tmp_path)
    assert corruption["failure_kind"] == "artifact_integrity_failed"
    assert any(issue.startswith("event_json_invalid:") for issue in corruption["issues"])

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["provenance"]["status"] = "mismatch"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    provenance = verify_runner_observability(summary_path, root=tmp_path)
    assert provenance["failure_kind"] == "provenance_mismatch"
    assert "provenance_mismatch" in provenance["issues"]
