from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from pcl.agent_exec import FAIL_MAX_BYTES, FAIL_MAX_LINES, gc_agent_exec, run_agent_exec
from pcl.errors import InvalidInputError


def test_large_simultaneous_stdout_stderr_is_drained_without_deadlock(tmp_path: Path) -> None:
    script = """
import os
import threading

def write_many(fd, byte):
    for _ in range(24):
        os.write(fd, byte * 65536)

threads = [
    threading.Thread(target=write_many, args=(1, b'o')),
    threading.Thread(target=write_many, args=(2, b'e')),
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
os.write(2, b'\\nRuntimeError: CONCURRENT_SENTINEL\\n')
raise SystemExit(5)
"""

    outcome = run_agent_exec(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=20,
        max_output_bytes=262_144,
        state_root=tmp_path / "state",
    )

    assert outcome.process_exit_code == 5
    assert outcome.result["status"] == "FAIL"
    assert outcome.result["raw"]["stdout_bytes"] > 1_000_000
    assert outcome.result["raw"]["stderr_bytes"] > 1_000_000
    assert "CONCURRENT_SENTINEL" in outcome.presentation
    assert len(outcome.presentation.splitlines()) <= FAIL_MAX_LINES
    assert len(outcome.presentation.encode("utf-8")) <= FAIL_MAX_BYTES


def test_utf8_boundary_is_decoded_after_bounded_byte_capture(tmp_path: Path) -> None:
    script = "import sys; sys.stdout.write('x'*65535 + '雪\\nAssertionError: UTF8_SENTINEL\\n'); raise SystemExit(6)"

    outcome = run_agent_exec(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=10,
        max_output_bytes=262_144,
        state_root=tmp_path / "state",
    )

    assert outcome.process_exit_code == 6
    assert "UTF8_SENTINEL" in outcome.presentation
    assert "雪" in outcome.presentation


@pytest.mark.skipif(os.name != "posix", reason="symlink boundary is POSIX-specific")
def test_symlinked_state_root_is_rejected_before_spawn(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "state-link"
    symlink.symlink_to(target, target_is_directory=True)

    with pytest.raises(InvalidInputError, match="symlinked agent execution state root"):
        run_agent_exec(
            [sys.executable, "-c", "print('must-not-run')"],
            cwd=tmp_path,
            timeout_seconds=5,
            max_output_bytes=1024,
            state_root=symlink,
        )

    assert list(target.iterdir()) == []


def test_invalid_custom_redaction_pattern_fails_before_state_creation(tmp_path: Path) -> None:
    state_root = tmp_path / "state"

    with pytest.raises(InvalidInputError):
        run_agent_exec(
            [sys.executable, "-c", "print('must-not-run')"],
            cwd=tmp_path,
            timeout_seconds=5,
            max_output_bytes=1024,
            redaction_patterns=["["],
            state_root=state_root,
        )

    assert not state_root.exists()


def test_total_byte_retention_removes_oldest_safe_runs_first(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    date_dir = state_root / "2026-08-30"
    date_dir.mkdir(parents=True)
    run_ids = [
        "AX-20260830T000001Z-000000000001",
        "AX-20260830T000002Z-000000000002",
        "AX-20260830T000003Z-000000000003",
    ]
    for index, run_id in enumerate(run_ids, start=1):
        run_dir = date_dir / run_id
        run_dir.mkdir()
        (run_dir / "meta.json").write_bytes(b"x" * 100)
        os.utime(run_dir, (index, index))

    result = gc_agent_exec(
        state_root=state_root,
        dry_run=False,
        now_timestamp=10,
        retention_seconds=1_000_000,
        total_limit_bytes=150,
    )

    assert result["removed_run_ids"] == run_ids[:2]
    assert not (date_dir / run_ids[0]).exists()
    assert not (date_dir / run_ids[1]).exists()
    assert (date_dir / run_ids[2]).exists()
