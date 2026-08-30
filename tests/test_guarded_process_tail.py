from __future__ import annotations

from pathlib import Path
import sys

from pcl.guarded_process import execute_guarded_process


def test_optional_tail_capture_preserves_default_head_contract(tmp_path: Path) -> None:
    stdout_path = tmp_path / "stdout.bin"
    stderr_path = tmp_path / "stderr.bin"
    stdout_tail_path = tmp_path / "stdout-tail.bin"
    stderr_tail_path = tmp_path / "stderr-tail.bin"
    script = "import sys; sys.stdout.write('A'*200 + 'TAIL_SENTINEL')"

    result = execute_guarded_process(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        stdout_tail_path=stdout_tail_path,
        stderr_tail_path=stderr_tail_path,
        timeout_seconds=5,
        max_output_bytes=32,
        tail_output_bytes=32,
    )

    assert result["exit_code"] == 0
    assert result["stdout"]["truncated"] is True
    assert result["stdout"]["capture_strategy"] == "head"
    assert stdout_path.read_bytes() == b"A" * 32
    assert result["stdout"]["tail"]["capture_strategy"] == "tail"
    assert result["stdout"]["tail"]["persisted"] is True
    assert b"TAIL_SENTINEL" in stdout_tail_path.read_bytes()
    assert stderr_tail_path.read_bytes() == b""


def test_default_guarded_process_result_shape_does_not_add_tail_metadata(tmp_path: Path) -> None:
    result = execute_guarded_process(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.bin",
        stderr_path=tmp_path / "stderr.bin",
        timeout_seconds=5,
        max_output_bytes=32,
    )

    assert result["exit_code"] == 0
    assert "tail" not in result["stdout"]
    assert "tail" not in result["stderr"]


def test_tail_capture_is_redacted_before_temporary_artifact_storage(tmp_path: Path) -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    stdout_tail_path = tmp_path / "stdout-tail.bin"
    result = execute_guarded_process(
        [sys.executable, "-c", f"print('x'*200 + '{secret}')"],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.bin",
        stderr_path=tmp_path / "stderr.bin",
        stdout_tail_path=stdout_tail_path,
        stderr_tail_path=tmp_path / "stderr-tail.bin",
        timeout_seconds=5,
        max_output_bytes=32,
        tail_output_bytes=96,
    )

    assert result["redacted"] is True
    assert secret.encode() not in stdout_tail_path.read_bytes()
    assert result["stdout"]["tail"]["redacted"] is True
