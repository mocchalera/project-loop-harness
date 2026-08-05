from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from pcl.contracts.runner_execution_receipt import (
    compute_cross_attempt_binding_sha256,
    compute_runner_execution_receipt_sha256,
    finalize_runner_execution_receipt,
    runner_execution_receipt_schema,
    validate_runner_execution_receipt,
)
from pcl.guarded_process import execute_guarded_process
from pcl.runner_execution_receipt import (
    MAX_RUNNER_FRAME_BYTES,
    RunnerExecutionReceiptError,
    RunnerExecutionReceiptRecorder,
    hash_file,
    platform_capability,
    verify_runner_execution_receipt,
)
from pcl.runner_observability import _write_summary_payload


def _run(
    root: Path,
    script: str,
    *,
    attempt_id: str = "attempt-test",
    attempt_index: int = 0,
    previous_attempt_id: str | None = None,
    previous_receipt_sha256: str | None = None,
    timeout_seconds: int = 5,
) -> dict:
    return execute_guarded_process(
        [sys.executable, "-c", script],
        cwd=root,
        stdout_path=root / "stdout.txt",
        stderr_path=root / "stderr.txt",
        timeout_seconds=timeout_seconds,
        observability_summary_path=root / "summary.json",
        observability_events_path=root / "events.jsonl",
        runner_execution_receipt_path=root / "receipt.json",
        attempt_id=attempt_id,
        attempt_index=attempt_index,
        previous_attempt_id=previous_attempt_id,
        previous_receipt_sha256=previous_receipt_sha256,
    )


def _child_frame_script() -> str:
    return (
        "from pcl.runner_observability import emit_child_observation_frame; "
        "emit_child_observation_frame('child_probe', value='diagnostic'); print('ok')"
    )


def test_schema_and_canonical_hash_are_strict_and_write_once(tmp_path: Path) -> None:
    result = _run(tmp_path, _child_frame_script())
    receipt = result["runner_execution_receipt"]

    assert runner_execution_receipt_schema()["title"] == "runner-execution-receipt/v1"
    assert validate_runner_execution_receipt(receipt).ok is True
    assert receipt["receipt_sha256"] == compute_runner_execution_receipt_sha256(receipt)
    assert receipt["cross_attempt_binding_sha256"] == compute_cross_attempt_binding_sha256(receipt)
    assert receipt["child_observation"]["authority"] == "non_authoritative"

    recorder = RunnerExecutionReceiptRecorder(
        receipt_path=tmp_path / "one-shot.json",
        requested_argv=["python", "-c", "pass"],
        spawned_argv=["python", "-c", "pass"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
        timeout_seconds=1,
    )
    empty_hash = "sha256:" + ("0" * 64)
    recorder.seal(
        spawn_status="failed",
        spawn_error_kind="not_found",
        pid=None,
        pgid=None,
        exit_code=None,
        timed_out=False,
        termination={
            "requested": False,
            "method": "not_started",
            "escalated": False,
            "term_sent": False,
            "kill_sent": False,
            "group_state": "not_started",
            "leader_alive": False,
            "pipes_eof": True,
        },
        stdout_sha256=empty_hash,
        stderr_sha256=empty_hash,
        stdout_eof=True,
        stderr_eof=True,
    )
    with pytest.raises(RunnerExecutionReceiptError, match="cannot be sealed twice"):
        recorder.seal(
            spawn_status="failed",
            spawn_error_kind="not_found",
            pid=None,
            pgid=None,
            exit_code=None,
            timed_out=False,
            termination={"group_state": "not_started", "pipes_eof": True},
            stdout_sha256=empty_hash,
            stderr_sha256=empty_hash,
            stdout_eof=True,
            stderr_eof=True,
        )


def test_normal_success_is_parent_bound_and_pipe_eof_is_recorded(tmp_path: Path) -> None:
    result = _run(tmp_path, _child_frame_script())
    receipt = result["runner_execution_receipt"]

    assert result["exit_code"] == 0
    assert receipt["spawn"]["status"] == "spawned"
    assert receipt["requested_argv_sha256"] == receipt["spawned_argv_sha256"]
    assert receipt["pid"] is not None
    assert receipt["pgid"] is not None
    assert receipt["event_sequence"] == 1
    assert receipt["dropped_count"] == 0
    assert receipt["eof"] == {"stdout": True, "stderr": True, "frames": True}
    assert receipt["stdout_sha256"] == hash_file(tmp_path / "stdout.txt")
    assert receipt["stderr_sha256"] == hash_file(tmp_path / "stderr.txt")
    assert receipt["platform_capability"]["process_group"] == "uncertain"
    assert verify_runner_execution_receipt(tmp_path / "receipt.json")["ok"] is True


def test_timeout_records_parent_termination_facts(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "import time; from pcl.runner_observability import emit_child_observation_frame; "
        "emit_child_observation_frame('started'); time.sleep(30)",
        timeout_seconds=1,
    )
    receipt = result["runner_execution_receipt"]

    assert result["timed_out"] is True
    assert receipt["timed_out"] is True
    assert receipt["exit_code"] is None
    assert receipt["termination"]["requested"] is True
    assert receipt["termination"]["term_sent"] is True
    assert receipt["eof"]["stdout"] is True
    assert receipt["eof"]["stderr"] is True


def test_spawn_failure_has_no_spawned_argv_or_pid(tmp_path: Path) -> None:
    result = execute_guarded_process(
        [str(tmp_path / "does-not-exist")],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.txt",
        stderr_path=tmp_path / "stderr.txt",
        timeout_seconds=5,
        runner_execution_receipt_path=tmp_path / "receipt.json",
        attempt_id="attempt-spawn-failure",
    )
    receipt = result["runner_execution_receipt"]

    assert result["spawn_error_kind"] == "not_found"
    assert receipt["spawn"] == {"status": "failed", "error_kind": "not_found"}
    assert receipt["spawned_argv_sha256"] is None
    assert receipt["pid"] is None
    assert receipt["termination"]["group_state"] == "not_started"
    assert verify_runner_execution_receipt(tmp_path / "receipt.json")["ok"] is True


def test_windows_capability_is_not_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    import pcl.runner_execution_receipt as receipt_runtime

    monkeypatch.setattr(receipt_runtime.os, "name", "nt")
    assert platform_capability(anonymous_pipe=False, group_state="unknown") == {
        "os": "windows",
        "anonymous_pipe": "not_applicable",
        "process_group": "not_applicable",
        "status": "not_applicable",
    }


def test_posix_capability_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    import pcl.runner_execution_receipt as receipt_runtime

    monkeypatch.setattr(receipt_runtime.os, "name", "posix")
    capability = platform_capability(anonymous_pipe=True, group_state="gone")
    assert capability["anonymous_pipe"] == "available"
    assert capability["process_group"] == "uncertain"
    assert capability["status"] == "uncertain"


def test_partial_frame_and_pipe_drop_are_not_green(tmp_path: Path) -> None:
    partial_root = tmp_path / "partial"
    partial_root.mkdir()
    partial = _run(
        partial_root,
        "import os; os.write(int(os.environ['PCL_RUNNER_OBSERVABILITY_FRAME_FD']), b'{')",
    )
    partial_receipt = partial["runner_execution_receipt"]
    assert partial_receipt["eof"]["frames"] is True
    assert partial_receipt["dropped_count"] >= 1
    assert partial_receipt["child_observation"]["status"] == "partial"

    drop_root = tmp_path / "drop"
    drop_root.mkdir()
    dropped = _run(
        drop_root,
        "import os; fd = int(os.environ['PCL_RUNNER_OBSERVABILITY_FRAME_FD']); "
        f"os.write(fd, b'x' * {MAX_RUNNER_FRAME_BYTES + 1} + b'\\n')",
    )
    dropped_receipt = dropped["runner_execution_receipt"]
    assert dropped_receipt["eof"]["frames"] is True
    assert dropped_receipt["dropped_count"] >= 1
    assert dropped_receipt["child_observation"]["status"] == "partial"
    assert verify_runner_execution_receipt(drop_root / "receipt.json")["ok"] is True


def test_missing_and_partial_receipts_fail_closed(tmp_path: Path) -> None:
    missing = verify_runner_execution_receipt(tmp_path / "missing.json")
    assert missing["ok"] is False
    assert missing["failure_kind"] == "receipt_invalid"

    partial_path = tmp_path / "partial.json"
    partial_path.write_bytes(b'{"contract_version":"runner-execution-receipt/v1"')
    partial = verify_runner_execution_receipt(partial_path)
    assert partial["ok"] is False
    assert partial["failure_kind"] == "receipt_invalid"


def test_cross_attempt_binding_rejects_replay_or_mixed_previous_receipt(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    first_root.mkdir()
    first = _run(first_root, _child_frame_script(), attempt_id="attempt-first")
    first_receipt = first["runner_execution_receipt"]

    second_root = tmp_path / "second"
    second_root.mkdir()
    _run(
        second_root,
        _child_frame_script(),
        attempt_id="attempt-second",
        attempt_index=1,
        previous_attempt_id="attempt-first",
        previous_receipt_sha256=first_receipt["receipt_sha256"],
    )
    assert verify_runner_execution_receipt(
        second_root / "receipt.json",
        expected_attempt_id="attempt-second",
        expected_previous_receipt_sha256=first_receipt["receipt_sha256"],
    )["ok"] is True

    mixed = json.loads((second_root / "receipt.json").read_text(encoding="utf-8"))
    mixed["previous_attempt_id"] = "attempt-other"
    mixed["previous_receipt_sha256"] = "sha256:" + ("0" * 64)
    mixed = finalize_runner_execution_receipt(mixed)
    (second_root / "mixed.json").write_text(json.dumps(mixed), encoding="utf-8")
    verification = verify_runner_execution_receipt(
        second_root / "mixed.json",
        expected_attempt_id="attempt-second",
        expected_previous_receipt_sha256=first_receipt["receipt_sha256"],
    )
    assert verification["ok"] is False
    assert "previous_receipt_hash_mismatch" in verification["issues"]
    assert mixed["previous_attempt_id"] == "attempt-other"
    assert validate_runner_execution_receipt(mixed).ok is True


@pytest.mark.parametrize(
    "rewrite",
    ["collection", "event", "termination", "dropped_count", "provenance", "summary", "result"],
)
def test_self_rehashed_child_sidecars_never_verify_as_parent_receipt(
    tmp_path: Path,
    rewrite: str,
) -> None:
    _run(tmp_path, _child_frame_script())
    summary_path = tmp_path / "summary.json"
    events_path = tmp_path / "events.jsonl"
    receipt_path = tmp_path / "receipt.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    if rewrite == "event":
        events_path.write_text('{"event":"rewritten"}\n', encoding="utf-8")
    else:
        if rewrite == "collection":
            payload["collection"]["collected_count"] = 999
        elif rewrite == "termination":
            payload["termination"]["requested"] = True
        elif rewrite == "dropped_count":
            payload["event_log"]["dropped_count"] = 999
        elif rewrite == "provenance":
            payload["provenance"]["status"] = "mismatch"
        elif rewrite == "summary":
            payload["status"] = "partial"
        elif rewrite == "result":
            result_path = tmp_path / "result.json"
            result_path.write_text('{"status":"rewritten"}\n', encoding="utf-8")
            payload["artifacts"]["result"] = {
                "path": "result.json",
                "sha256": hash_file(result_path),
            }
        _write_summary_payload(summary_path, payload)

    assert verify_runner_execution_receipt(receipt_path)["ok"] is True
    verification = verify_runner_execution_receipt(
        receipt_path,
        summary_path=summary_path,
        events_path=events_path,
        result_path=(tmp_path / "result.json") if rewrite == "result" else None,
    )
    assert verification["ok"] is False
    if rewrite == "event":
        assert "child_events_hash_mismatch" in verification["issues"]
    elif rewrite == "result":
        assert "result_unbound_by_receipt" in verification["issues"]
    else:
        assert "child_summary_hash_mismatch" in verification["issues"]
