from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import tracemalloc

from pcl.guarded_process import build_subprocess_env, execute_guarded_process
from pcl.redaction import REDACTED_SECRET, compile_redaction_patterns


def _run(
    tmp_path: Path,
    script: str,
    *,
    timeout_seconds: int = 5,
    max_output_bytes: int = 4096,
    redaction_patterns: tuple[str, ...] = (),
):
    return execute_guarded_process(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.bin",
        stderr_path=tmp_path / "stderr.bin",
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        redaction_patterns=compile_redaction_patterns(redaction_patterns),
    )


def test_large_stdout_and_stderr_are_streamed_with_bounded_capture(tmp_path: Path) -> None:
    script = "import os; os.write(1, b'x' * 8000000); os.write(2, b'y' * 7000000)"
    tracemalloc.start()
    result = _run(tmp_path, script, max_output_bytes=4096)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert result["exit_code"] == 0
    assert result["output_truncated"] is True
    assert result["stdout"]["original_byte_count"] == 8_000_000
    assert result["stderr"]["original_byte_count"] == 7_000_000
    assert result["stdout"]["captured_byte_count"] == 4096
    assert result["stderr"]["captured_byte_count"] == 4096
    assert result["stdout"]["truncation_reason"] == "max_output_bytes_exceeded"
    assert result["stdout"]["capture_strategy"] == "head"
    assert (tmp_path / "stdout.bin").stat().st_size == 4096
    assert (tmp_path / "stderr.bin").stat().st_size == 4096
    assert peak_bytes < 2_000_000


def test_timeout_terminates_process_group_and_records_reason(tmp_path: Path) -> None:
    started = time.monotonic()
    result = _run(tmp_path, "import time; print('started', flush=True); time.sleep(30)", timeout_seconds=1)

    assert time.monotonic() - started < 5
    assert result["exit_code"] is None
    assert result["timed_out"] is True
    assert result["failure_kind"] == "timeout"
    assert result["termination"]["requested"] is True
    assert result["termination"]["method"] == "terminate_process_group"


def test_redaction_filters_positive_and_negative_fixtures_before_write(tmp_path: Path) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    result = _run(
        tmp_path,
        f"print({secret!r}); print('ORDER-123'); print('ordinary-value')",
        redaction_patterns=(r"ORDER-\d+",),
    )
    stored = (tmp_path / "stdout.bin").read_text(encoding="utf-8")

    assert result["redacted"] is True
    assert result["stdout"]["raw_output_persisted"] is False
    assert secret not in stored
    assert "ORDER-123" not in stored
    assert stored.count(REDACTED_SECRET) == 2
    assert "ordinary-value" in stored


def test_binary_output_preserves_invalid_utf8_and_reports_encoding(tmp_path: Path) -> None:
    result = _run(tmp_path, "import os; os.write(1, b'prefix\\xffsuffix')")

    assert result["stdout"]["binary"] is True
    assert result["stdout"]["encoding"] is None
    assert (tmp_path / "stdout.bin").read_bytes() == b"prefix\xffsuffix"


def test_environment_uses_allowlist_and_does_not_inherit_secret(monkeypatch) -> None:
    monkeypatch.setenv("PCL_TEST_SECRET", "must-not-leak")
    monkeypatch.setenv("PCL_TEST_ALLOWED", "allowed-value")

    env, contract = build_subprocess_env(additional_allowed_names={"PCL_TEST_ALLOWED"})

    assert env["PCL_TEST_ALLOWED"] == "allowed-value"
    assert "PCL_TEST_SECRET" not in env
    assert "PCL_TEST_ALLOWED" in contract["inherited_names"]
    assert contract["inheritance"] == "allowlist"
    assert contract["values_recorded"] is False
    assert os.environ["PCL_TEST_SECRET"] == "must-not-leak"
