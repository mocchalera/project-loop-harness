from __future__ import annotations

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


DEFAULT_MAX_OUTPUT_BYTES = 1_048_576
READ_CHUNK_BYTES = 65_536
DEFAULT_ENV_ALLOWLIST = frozenset(
    {
        "CI",
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
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "VIRTUAL_ENV",
    }
)


class _BoundedStream:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.captured_byte_count = 0
        self.original_byte_count = 0
        self.file = tempfile.TemporaryFile(mode="w+b")

    def consume(self, chunk: bytes) -> None:
        self.original_byte_count += len(chunk)
        remaining = self.max_bytes - self.captured_byte_count
        if remaining > 0:
            retained = chunk[:remaining]
            self.file.write(retained)
            self.captured_byte_count += len(retained)

    def read(self) -> bytes:
        self.file.flush()
        self.file.seek(0)
        return self.file.read()

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
    redaction_patterns: Iterable[Pattern[str]] = (),
    additional_allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be at least 1")
    patterns = tuple(redaction_patterns)
    env, environment_contract = build_subprocess_env(
        additional_allowed_names=additional_allowed_env_names
    )
    stdout_capture = _BoundedStream(max_output_bytes)
    stderr_capture = _BoundedStream(max_output_bytes)
    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    spawn_error = ""
    termination = {"requested": False, "method": "", "escalated": False}

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            text=False,
            start_new_session=True,
        )
    except OSError as exc:
        spawn_error = f"{exc.__class__.__name__}: {exc}\n"
        stderr_capture.consume(spawn_error.encode("utf-8", errors="replace"))
    else:
        assert process.stdout is not None
        assert process.stderr is not None
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
            for thread in threads:
                thread.join(timeout=2)
            process.stdout.close()
            process.stderr.close()

    if timed_out and stderr_capture.original_byte_count == 0:
        stderr_capture.consume(f"Timed out after {timeout_seconds} seconds.\n".encode())
    stdout_metadata = _write_capture(
        stdout_capture,
        stdout_path,
        redaction_patterns=patterns,
    )
    stderr_metadata = _write_capture(
        stderr_capture,
        stderr_path,
        redaction_patterns=patterns,
    )
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 6),
        "failure_kind": "spawn_error" if spawn_error else ("timeout" if timed_out else ""),
        "stdout": stdout_metadata,
        "stderr": stderr_metadata,
        "output_truncated": stdout_metadata["truncated"] or stderr_metadata["truncated"],
        "redacted": stdout_metadata["redacted"] or stderr_metadata["redacted"],
        "termination": termination,
        "permission_contract": {
            "backend": "host_subprocess",
            "argv": list(argv),
            "shell": False,
            "working_directory": str(cwd),
            "environment": environment_contract,
            "isolation": {
                "os": False,
                "network": False,
                "filesystem": False,
            },
        },
    }


def _drain_stream(stream: Any, capture: _BoundedStream) -> None:
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        if not chunk:
            return
        capture.consume(chunk)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    result = {"requested": True, "method": "terminate_process_group", "escalated": False}
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            result["escalated"] = True
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=1)
    return result


def _write_capture(
    capture: _BoundedStream,
    path: Path,
    *,
    redaction_patterns: tuple[Pattern[str], ...],
) -> dict[str, Any]:
    try:
        captured = capture.read()
        redacted, changed = redact_bytes(captured, additional_patterns=redaction_patterns)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(redacted)
    finally:
        capture.close()
    try:
        redacted.decode("utf-8")
    except UnicodeDecodeError:
        encoding: str | None = None
        binary = True
    else:
        encoding = "utf-8"
        binary = False
    truncated = capture.original_byte_count > len(captured)
    return {
        "path": str(path),
        "original_byte_count": capture.original_byte_count,
        "captured_byte_count": len(captured),
        "artifact_byte_count": len(redacted),
        "max_bytes": capture.max_bytes,
        "truncated": truncated,
        "truncation_reason": "max_output_bytes_exceeded" if truncated else "",
        "capture_strategy": "head",
        "capture_mode": "streaming_temporary_file",
        "redacted": changed,
        "raw_output_persisted": False,
        "encoding": encoding,
        "binary": binary,
    }
