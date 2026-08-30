from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Pattern
import uuid

from .errors import DataStoreError, InvalidInputError
from .guarded_process import execute_guarded_process
from .redaction import compile_redaction_patterns, redact_text


RESULT_SCHEMA = "agent-exec-result/v1"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
DEFAULT_RETENTION_HOURS = 72
DEFAULT_TOTAL_BYTES = 512 * 1024 * 1024
MAX_DIAGNOSTIC_LINES = 117
MAX_DIAGNOSTIC_BYTES = 16 * 1024
MAX_PRESENTATION_LINES = 120
MAX_PRESENTATION_BYTES = 24 * 1024
PASS_MAX_LINES = 5
PASS_MAX_BYTES = 2 * 1024
RUN_ID_RE = re.compile(r"^AX-(\d{8})-([a-f0-9]{24})$")
ERROR_LINE_RE = re.compile(
    r"(?i)(?:^|\b)(failed|failure|error|assertionerror|traceback|exception|panic|"
    r"permission denied|not found|timed out|timeout)(?:\b|:)",
)
SECRET_OPTION_RE = re.compile(
    r"(?i)(?:^|[-_])(api[-_]?key|token|secret|password|private[-_]?key)$"
)


class AgentExecStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()

    @classmethod
    def from_override(cls, override: str | None) -> "AgentExecStore":
        if override:
            return cls(Path(override))
        env_override = os.environ.get("PCL_AGENT_EXEC_STATE_DIR")
        if env_override:
            return cls(Path(env_override))
        xdg_state = os.environ.get("XDG_STATE_HOME")
        if xdg_state:
            return cls(Path(xdg_state) / "project-loop-harness" / "agent-exec")
        if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
            return cls(Path(os.environ["LOCALAPPDATA"]) / "ProjectLoopHarness" / "agent-exec")
        return cls(Path.home() / ".local" / "state" / "project-loop-harness" / "agent-exec")

    def create_run(self, *, now: datetime | None = None) -> tuple[str, Path]:
        timestamp = now or datetime.now(timezone.utc)
        day = timestamp.strftime("%Y-%m-%d")
        prefix = timestamp.strftime("%Y%m%d")
        day_dir = self.root / day
        _ensure_private_directory(self.root)
        _ensure_private_directory(day_dir)
        for _ in range(8):
            run_id = f"AX-{prefix}-{uuid.uuid4().hex[:24]}"
            run_dir = day_dir / run_id
            try:
                os.mkdir(run_dir, 0o700)
            except FileExistsError:
                continue
            _chmod_private(run_dir, directory=True)
            return run_id, run_dir
        raise DataStoreError("Could not allocate a unique agent-exec run directory.")

    def run_dir(self, run_id: str) -> Path:
        match = RUN_ID_RE.fullmatch(run_id)
        if not match:
            raise InvalidInputError(
                "Invalid agent-exec run id.", details={"run_id": run_id}
            )
        day_token = match.group(1)
        day = f"{day_token[:4]}-{day_token[4:6]}-{day_token[6:8]}"
        path = self.root / day / run_id
        if path.is_symlink():
            raise DataStoreError("Agent-exec run directory must not be a symlink.")
        return path

    def write_metadata(self, run_dir: Path, payload: dict[str, Any]) -> None:
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        _atomic_private_write(run_dir / "meta.json", encoded)

    def write_diagnostic(self, run_dir: Path, text: str) -> None:
        _atomic_private_write(run_dir / "diagnostic.redacted.log", text.encode("utf-8"))

    def read_metadata(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / "meta.json"
        return _read_json_file(path, expected_name="agent-exec metadata")

    def read_diagnostic(self, run_id: str) -> str:
        path = self.run_dir(run_id) / "diagnostic.redacted.log"
        if path.is_symlink():
            raise DataStoreError("Agent-exec diagnostic must not be a symlink.")
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise InvalidInputError(
                "No diagnostic is retained for this run.", details={"run_id": run_id}
            ) from exc
        except OSError as exc:
            raise DataStoreError(f"Could not read agent-exec diagnostic: {exc}") from exc
        return data.decode("utf-8", errors="replace")

    def collect_garbage(
        self,
        *,
        dry_run: bool,
        now: datetime | None = None,
        max_age_hours: int = DEFAULT_RETENTION_HOURS,
        max_total_bytes: int = DEFAULT_TOTAL_BYTES,
    ) -> dict[str, Any]:
        if max_age_hours < 1 or max_total_bytes < 1:
            raise InvalidInputError("Retention limits must be positive integers.")
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(hours=max_age_hours)
        entries: list[dict[str, Any]] = []
        if self.root.exists():
            if self.root.is_symlink():
                raise DataStoreError("Agent-exec state directory must not be a symlink.")
            for day_dir in sorted(self.root.iterdir()):
                if not day_dir.is_dir() or day_dir.is_symlink():
                    continue
                for run_dir in sorted(day_dir.iterdir()):
                    if not run_dir.is_dir() or run_dir.is_symlink():
                        continue
                    match = RUN_ID_RE.fullmatch(run_dir.name)
                    if not match:
                        continue
                    stat = run_dir.stat()
                    entries.append(
                        {
                            "path": run_dir,
                            "run_id": run_dir.name,
                            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                            "bytes": _directory_bytes(run_dir),
                        }
                    )
        entries.sort(key=lambda row: (row["mtime"], row["run_id"]))
        selected: list[dict[str, Any]] = [row for row in entries if row["mtime"] < cutoff]
        selected_ids = {row["run_id"] for row in selected}
        remaining_bytes = sum(row["bytes"] for row in entries if row["run_id"] not in selected_ids)
        if remaining_bytes > max_total_bytes:
            for row in entries:
                if row["run_id"] in selected_ids:
                    continue
                selected.append(row)
                selected_ids.add(row["run_id"])
                remaining_bytes -= row["bytes"]
                if remaining_bytes <= max_total_bytes:
                    break
        selected_bytes = sum(row["bytes"] for row in selected)
        failures: list[dict[str, str]] = []
        removed_ids: set[str] = set()
        if dry_run:
            removed_ids = set(selected_ids)
        else:
            for row in selected:
                try:
                    shutil.rmtree(row["path"])
                except OSError as exc:
                    failures.append({"run_id": row["run_id"], "error": str(exc)})
                else:
                    removed_ids.add(row["run_id"])
            _remove_empty_day_directories(self.root)
        retained = [row for row in entries if row["run_id"] not in removed_ids]
        return {
            "ok": not failures,
            "schema": "agent-exec-gc/v1",
            "dry_run": dry_run,
            "selected_runs": [row["run_id"] for row in selected],
            "selected_count": len(selected),
            "selected_bytes": selected_bytes,
            "retained_count": len(retained),
            "retained_bytes": sum(row["bytes"] for row in retained),
            "limits": {
                "max_age_hours": max_age_hours,
                "max_total_bytes": max_total_bytes,
            },
            "failures": failures,
        }


def run_agent_command(
    argv: list[str],
    *,
    cwd: Path,
    store: AgentExecStore,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_CAPTURE_BYTES,
    redaction_patterns: Iterable[str] = (),
    allowed_env_names: Iterable[str] = (),
) -> tuple[dict[str, Any], int, list[str]]:
    if not argv:
        raise InvalidInputError("`pcl exec --` requires at least one argv token.")
    if timeout_seconds < 1 or timeout_seconds > 86_400:
        raise InvalidInputError(
            "--timeout-seconds must be between 1 and 86400.",
            details={"timeout_seconds": timeout_seconds},
        )
    if max_output_bytes < 1024 or max_output_bytes > MAX_CAPTURE_BYTES:
        raise InvalidInputError(
            f"--max-output-bytes must be between 1024 and {MAX_CAPTURE_BYTES}.",
            details={"max_output_bytes": max_output_bytes},
        )
    compiled_patterns = compile_redaction_patterns(redaction_patterns)
    run_id, run_dir = store.create_run()
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with tempfile.TemporaryDirectory(prefix="pcl-agent-exec-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        stdout_path = temp_dir / "stdout.redacted.bin"
        stderr_path = temp_dir / "stderr.redacted.bin"
        result = execute_guarded_process(
            argv,
            cwd=cwd,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            redaction_patterns=compiled_patterns,
            additional_allowed_env_names=allowed_env_names,
            capture_strategy="head_tail",
            handle_interrupt=True,
        )
        stdout_bytes = stdout_path.read_bytes()
        stderr_bytes = stderr_path.read_bytes()
        diagnostic, diagnostic_meta = _extract_diagnostic(
            stdout_bytes,
            stderr_bytes,
            stdout_binary=bool(result["stdout"]["binary"]),
            stderr_binary=bool(result["stderr"]["binary"]),
        )
    status, shell_exit_code, signal_number = _classify_result(result)
    command_summary = _command_summary(argv, compiled_patterns)
    payload: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "ok": status == "PASS",
        "run_id": run_id,
        "created_at": created_at,
        "status": status,
        "exit_code": result.get("exit_code"),
        "shell_exit_code": shell_exit_code,
        "signal": signal_number,
        "duration_ms": int(round(float(result["duration_seconds"]) * 1000)),
        "command": command_summary,
        "raw": {
            "stdout_bytes": int(result["stdout"]["original_byte_count"]),
            "stderr_bytes": int(result["stderr"]["original_byte_count"]),
        },
        "capture": {
            "strategy": "head_tail",
            "max_bytes_per_stream": max_output_bytes,
            "stdout_truncated": bool(result["stdout"]["truncated"]),
            "stderr_truncated": bool(result["stderr"]["truncated"]),
            "redacted": bool(result["redacted"]),
        },
        "diagnostics": {
            "available": status != "PASS" and bool(diagnostic),
            "persisted": status != "PASS" and bool(diagnostic),
            "truncated": (
                bool(diagnostic_meta["truncated"]) if status != "PASS" else False
            ),
            "strategy": diagnostic_meta["strategy"] if status != "PASS" else "none",
            "line_count": int(diagnostic_meta["line_count"]) if status != "PASS" else 0,
            "byte_count": int(diagnostic_meta["byte_count"]) if status != "PASS" else 0,
            "preview": diagnostic.splitlines() if status != "PASS" and diagnostic else [],
        },
        "termination": {
            "requested": bool(result["termination"].get("requested")),
            "escalated": bool(result["termination"].get("escalated")),
            "group_state": str(result["termination"].get("group_state") or "unknown"),
            "group_uncertain": bool(result["termination"].get("group_uncertain")),
            "pipes_eof": bool(result["termination"].get("pipes_eof")),
        },
        "retry_count": 0,
    }
    human_lines = _render_run_lines(payload)
    payload["exposed"] = _measure_lines(human_lines)
    if status == "PASS":
        payload["diagnostics"]["preview"] = []
    elif diagnostic:
        store.write_diagnostic(run_dir, diagnostic)
    store.write_metadata(run_dir, payload)
    return payload, shell_exit_code, human_lines


def render_metadata(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def diagnostic_tail(text: str, line_count: int) -> str:
    if line_count < 1 or line_count > MAX_DIAGNOSTIC_LINES:
        raise InvalidInputError(
            f"--tail must be between 1 and {MAX_DIAGNOSTIC_LINES}.",
            details={"tail": line_count},
        )
    return "\n".join(text.splitlines()[-line_count:])


def _classify_result(result: dict[str, Any]) -> tuple[str, int, int | None]:
    if result.get("interrupted"):
        return "INTERRUPTED", 130, 2
    if result.get("timed_out"):
        return "TIMEOUT", 124, None
    if result.get("failure_kind") == "spawn_error":
        kind = result.get("spawn_error_kind")
        if kind == "not_found":
            return "INFRA_ERROR", 127, None
        if kind == "permission_denied":
            return "INFRA_ERROR", 126, None
        return "INFRA_ERROR", 125, None
    exit_code = result.get("exit_code")
    if exit_code == 0:
        return "PASS", 0, None
    if isinstance(exit_code, int) and exit_code < 0:
        signal_number = abs(exit_code)
        return "FAIL", min(255, 128 + signal_number), signal_number
    if isinstance(exit_code, int):
        return "FAIL", max(1, min(255, exit_code)), None
    return "INFRA_ERROR", 125, None


def _command_summary(argv: list[str], patterns: tuple[Pattern[str], ...]) -> dict[str, Any]:
    redacted_argv, changed = _redact_argv(argv, patterns)
    executable = Path(redacted_argv[0]).name or "[unknown]"
    canonical = json.dumps(
        redacted_argv,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "executable": executable,
        "argument_count": max(0, len(argv) - 1),
        "argv_sha256": f"sha256:{hashlib.sha256(canonical).hexdigest()}",
        "redacted": changed,
        "argv_omitted": True,
    }


def _redact_argv(argv: list[str], patterns: tuple[Pattern[str], ...]) -> tuple[list[str], bool]:
    result: list[str] = []
    changed = False
    redact_next = False
    for token in argv:
        if redact_next:
            result.append("[REDACTED_SECRET]")
            changed = True
            redact_next = False
            continue
        redacted, item_changed = redact_text(token, additional_patterns=patterns)
        result.append(redacted)
        changed = changed or item_changed
        option_name = token.split("=", 1)[0].lstrip("-")
        if "=" not in token and SECRET_OPTION_RE.search(option_name):
            redact_next = True
    return result, changed


def _extract_diagnostic(
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    *,
    stdout_binary: bool,
    stderr_binary: bool,
) -> tuple[str, dict[str, Any]]:
    stdout_lines = _decode_lines(stdout_bytes, binary=stdout_binary, label="stdout")
    stderr_lines = _decode_lines(stderr_bytes, binary=stderr_binary, label="stderr")
    candidates: list[str] = []
    seen: set[tuple[str, int]] = set()
    for label, lines in (("stderr", stderr_lines), ("stdout", stdout_lines)):
        for index, line in enumerate(lines):
            if not ERROR_LINE_RE.search(line):
                continue
            start = max(0, index - 3)
            end = min(len(lines), index + 5)
            for cursor in range(start, end):
                key = (label, cursor)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(f"[{label}] {lines[cursor]}")
    strategy_parts: list[str] = []
    if candidates:
        strategy_parts.append("error-block")
    stderr_tail = [f"[stderr] {line}" for line in stderr_lines[-40:]]
    stdout_tail = [f"[stdout] {line}" for line in stdout_lines[-20:]]
    if stderr_tail:
        strategy_parts.append("stderr-tail")
    if stdout_tail:
        strategy_parts.append("stdout-tail")
    combined = _dedupe_preserving_order([*candidates, *stderr_tail, *stdout_tail])
    if not combined:
        combined = ["No textual diagnostic output was captured."]
        strategy_parts.append("empty")
    bounded, truncated = _bound_text_lines(
        combined,
        max_lines=MAX_DIAGNOSTIC_LINES,
        max_bytes=MAX_DIAGNOSTIC_BYTES,
    )
    text = "\n".join(bounded)
    return text, {
        "strategy": "+".join(strategy_parts),
        "truncated": truncated,
        "line_count": len(bounded),
        "byte_count": len(text.encode("utf-8")),
    }


def _decode_lines(value: bytes, *, binary: bool, label: str) -> list[str]:
    if not value:
        return []
    if binary:
        return [f"<{label} contained binary or invalid UTF-8 output; text omitted>"]
    return value.decode("utf-8", errors="replace").splitlines()


def _dedupe_preserving_order(lines: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


def _render_run_lines(payload: dict[str, Any]) -> list[str]:
    status = payload["status"]
    raw_total = payload["raw"]["stdout_bytes"] + payload["raw"]["stderr_bytes"]
    first = (
        f"{status} run={payload['run_id']} exit={payload['shell_exit_code']} "
        f"duration={payload['duration_ms']}ms raw={raw_total}B"
    )
    if status == "PASS":
        lines, _ = _bound_text_lines([first], max_lines=PASS_MAX_LINES, max_bytes=PASS_MAX_BYTES)
        return lines
    preview = list(payload["diagnostics"].get("preview") or [])
    lines = [first, *preview, f"inspect: pcl exec show {payload['run_id']} --errors"]
    bounded, _ = _bound_text_lines(
        lines,
        max_lines=MAX_PRESENTATION_LINES,
        max_bytes=MAX_PRESENTATION_BYTES,
    )
    return bounded


def _bound_text_lines(
    lines: Iterable[str],
    *,
    max_lines: int,
    max_bytes: int,
) -> tuple[list[str], bool]:
    result: list[str] = []
    used = 0
    truncated = False
    for line in lines:
        if len(result) >= max_lines:
            truncated = True
            break
        normalized = line.replace("\x00", "�")
        encoded = normalized.encode("utf-8")
        separator = 1 if result else 0
        remaining = max_bytes - used - separator
        if remaining <= 0:
            truncated = True
            break
        if len(encoded) > remaining:
            clipped = encoded[:remaining].decode("utf-8", errors="ignore")
            if clipped:
                result.append(clipped)
            truncated = True
            break
        result.append(normalized)
        used += separator + len(encoded)
    return result, truncated


def _measure_lines(lines: list[str]) -> dict[str, int]:
    text = "\n".join(lines)
    return {"lines": len(lines), "bytes": len(text.encode("utf-8"))}


def _ensure_private_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise DataStoreError(f"State directory must not be a symlink: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        _chmod_private(path, directory=True)
    except OSError as exc:
        raise DataStoreError(f"Could not create private state directory: {exc}") from exc


def _chmod_private(path: Path, *, directory: bool) -> None:
    if os.name == "posix":
        os.chmod(path, 0o700 if directory else 0o600)


def _atomic_private_write(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise DataStoreError(f"Refusing to overwrite agent-exec state file: {path.name}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_private(temporary, directory=False)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except TypeError:  # pragma: no cover - older platform signature
            os.link(temporary, path)
        _chmod_private(path, directory=False)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise DataStoreError(f"Could not write agent-exec state: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json_file(path: Path, *, expected_name: str) -> dict[str, Any]:
    if path.is_symlink():
        raise DataStoreError(f"{expected_name} must not be a symlink.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvalidInputError(f"{expected_name.capitalize()} was not found.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DataStoreError(f"Could not read {expected_name}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != RESULT_SCHEMA:
        raise DataStoreError(f"Stored {expected_name} has an invalid contract.")
    return payload


def _directory_bytes(path: Path) -> int:
    total = 0
    for entry in path.iterdir():
        if entry.is_symlink():
            continue
        if entry.is_file():
            total += entry.stat().st_size
    return total


def _remove_empty_day_directories(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for day_dir in root.iterdir():
        if not day_dir.is_dir() or day_dir.is_symlink():
            continue
        try:
            day_dir.rmdir()
        except OSError:
            pass


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
