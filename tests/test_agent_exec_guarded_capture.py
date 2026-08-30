from __future__ import annotations

from pathlib import Path
import sys

import pytest

from pcl.guarded_process import execute_guarded_process


def test_head_tail_capture_retains_start_middle_error_and_tail(tmp_path: Path) -> None:
    script = (
        "import os, sys; "
        "os.write(1, b'HEAD-MARKER\\n' + b'a\\n' * 20000); "
        "os.write(1, b'AssertionError: MIDDLE-MARKER\\n'); "
        "os.write(1, b'z\\n' * 20000 + b'TAIL-MARKER\\n'); "
        "sys.exit(9)"
    )
    result = execute_guarded_process(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.bin",
        stderr_path=tmp_path / "stderr.bin",
        timeout_seconds=10,
        max_output_bytes=4096,
        capture_strategy="head_tail",
    )
    stored = (tmp_path / "stdout.bin").read_bytes()

    assert result["exit_code"] == 9
    assert result["stdout"]["capture_strategy"] == "head_tail"
    assert result["stdout"]["capture_mode"] == "streaming_memory_head_tail_error_windows"
    assert result["stdout"]["captured_byte_count"] <= 4096
    assert result["stdout"]["truncated"] is True
    assert b"HEAD-MARKER" in stored
    assert b"AssertionError: MIDDLE-MARKER" in stored
    assert b"TAIL-MARKER" in stored
    assert b"PCL OUTPUT OMITTED" in stored


def test_default_capture_contract_remains_head_only(tmp_path: Path) -> None:
    result = execute_guarded_process(
        [sys.executable, "-c", "import os; os.write(1, b'a' * 10000)"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.bin",
        stderr_path=tmp_path / "stderr.bin",
        timeout_seconds=5,
        max_output_bytes=128,
    )

    assert result["stdout"]["capture_strategy"] == "head"
    assert result["stdout"]["capture_mode"] == "streaming_temporary_file"
    assert result["stdout"]["captured_byte_count"] == 128
    assert (tmp_path / "stdout.bin").read_bytes() == b"a" * 128


def test_unknown_capture_strategy_fails_before_spawn(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="capture_strategy"):
        execute_guarded_process(
            [sys.executable, "-c", "print('must not run')"],
            cwd=tmp_path,
            stdout_path=tmp_path / "stdout.bin",
            stderr_path=tmp_path / "stderr.bin",
            timeout_seconds=5,
            capture_strategy="unknown",
        )
