from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any, Iterable, Pattern

from .contracts.agent_exec_result import (
    AGENT_EXEC_RESULT_CONTRACT_VERSION,
    validate_agent_exec_result,
)
from .errors import InvalidInputError
from .guarded_process import execute_guarded_process
from .redaction import redact_bytes


PASS_MAX_LINES = 5
PASS_MAX_BYTES = 2_048
FAIL_MAX_LINES = 120
FAIL_MAX_BYTES = 24_576
MAX_OUTPUT_BYTES_PER_STREAM = 8 * 1024 * 1024
MAX_COMMAND_ITEM_BYTES = 256
MAX_COMMAND_TOTAL_BYTES = 2_048
MAX_DIAGNOSTIC_LINE_BYTES = 1_024
DEFAULT_RETENTION_SECONDS = 72 * 60 * 60
DEFAULT_TOTAL_RETENTION_BYTES = 512 * 1024 * 1024
REDACTED_ARGUMENT = "[REDACTED]"
RUN_ID_PATTERN = re.compile(r"^AX-(\d{8})T\d{6}Z-([a-f0-9]{12})$")
ERROR_LINE_PATTERN = re.compile(
    r"(?i)(?:\berror\b|\bfail(?:ed|ure)?\b|assert(?:ion)?|exception|traceback|"
    r"\bpanic\b|\bfatal\b|timed?\s*out|not found|permission denied|segmentation fault)"
)
SENSITIVE_OPTION_PATTERN = re.compile(
    r"^--?(?:api[-_]?key|token|secret|password|private[-_]?key)$",
    re.IGNORECASE,
)
UNIX_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![:/\w])/(?:[^\s:]+/)*[^\s:]+")
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"\b[A-Za-z]:\\[^\r\n\t]+")
EXPECTED_RUN_FILES = frozenset({"meta.json", "diagnostic.redacted.log"})


@dataclass(frozen=True)
class AgentExecOutcome:
    result: dict[str, Any]
    presentation: str
    process_exit_code: int


@dataclass(frozen=True)
class DiagnosticSelection:
    text: str
    strategy: str
    truncated: bool
    redacted: bool = False


def default_agent_exec_state_root() -> Path:
    override = os.environ.get("PCL_AGENT_EXEC_STATE_DIR")
    if override:
        return Path(override).expanduser()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state).expanduser() if xdg_state else Path.home() / ".local" / "state"
    return base / "project-loop-harness" / "agent-exec"


def run_agent_exec(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    redaction_patterns: Iterable[str] = (),
    allowed_env_names: Iterable[str] = (),
    state_root: Path | None = None,
) -> AgentExecOutcome:
    if not argv:
        raise InvalidInputError("`pcl exec --` requires at least one argv item.")
    if timeout_seconds < 1:
        raise InvalidInputError("--timeout-seconds must be at least 1.")
    if not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES_PER_STREAM:
        raise InvalidInputError(
            f"--max-output-bytes must be between 1 and {MAX_OUTPUT_BYTES_PER_STREAM}."
        )
    if len(argv) > 256:
        raise InvalidInputError("Agent execution argv is limited to 256 items.")
    if any("\x00" in item for item in argv):
        raise InvalidInputError("Agent execution argv cannot contain NUL bytes.")

    patterns = _compile_redaction_patterns(redaction_patterns)
    root = _prepare_state_root(state_root or default_agent_exec_state_root())
    run_id = _new_run_id()
    run_dir = _create_run_directory(root, run_id)
    redacted_command, command_redacted = _redact_argv(argv, patterns, cwd=cwd)
    head_bytes = max(1, max_output_bytes // 2)
    tail_bytes = max_output_bytes - head_bytes

    with tempfile.TemporaryDirectory(prefix="pcl-agent-exec-") as temp_name:
        temp_dir = Path(temp_name)
        execution = execute_guarded_process(
            list(argv),
            cwd=cwd,
            stdout_path=temp_dir / "stdout-head.redacted.bin",
            stderr_path=temp_dir / "stderr-head.redacted.bin",
            stdout_tail_path=temp_dir / "stdout-tail.redacted.bin",
            stderr_tail_path=temp_dir / "stderr-tail.redacted.bin",
            timeout_seconds=timeout_seconds,
            max_output_bytes=head_bytes,
            tail_output_bytes=tail_bytes,
            capture_interrupt=True,
            redaction_patterns=patterns,
            additional_allowed_env_names=allowed_env_names,
        )
        status, signal_number, process_exit_code = _classify_execution(execution)
        diagnostic = (
            DiagnosticSelection("", "none", False)
            if status == "PASS"
            else _sanitize_diagnostic(_select_diagnostic(execution), cwd=cwd)
        )

    diagnostic_available = status != "PASS" and bool(diagnostic.text)
    if diagnostic_available:
        try:
            _exclusive_write(
                run_dir / "diagnostic.redacted.log",
                diagnostic.text.encode("utf-8"),
            )
        except OSError:
            diagnostic_available = False

    result: dict[str, Any] = {
        "schema": AGENT_EXEC_RESULT_CONTRACT_VERSION,
        "run_id": run_id,
        "status": status,
        "exit_code": execution.get("exit_code"),
        "signal": signal_number,
        "duration_ms": max(0, round(float(execution.get("duration_seconds", 0)) * 1000)),
        "command": redacted_command,
        "command_redacted": command_redacted,
        "raw": {
            "stdout_bytes": int(execution["stdout"]["original_byte_count"]),
            "stderr_bytes": int(execution["stderr"]["original_byte_count"]),
        },
        "exposed": {"lines": 0, "bytes": 0},
        "diagnostics": {
            "available": diagnostic_available,
            "truncated": bool(diagnostic.truncated or execution.get("output_truncated")),
            "strategy": diagnostic.strategy,
            "line_count": _line_count(diagnostic.text),
            "byte_count": len(diagnostic.text.encode("utf-8")),
        },
        "redacted": bool(execution.get("redacted") or command_redacted or diagnostic.redacted),
        "output_truncated": bool(execution.get("output_truncated")),
        "termination": _compact_termination(execution.get("termination", {})),
        "retry_count": 0,
    }
    presentation = _stabilize_presentation(result, diagnostic.text)
    validation = validate_agent_exec_result(result)
    if not validation.ok:
        raise RuntimeError("invalid internal agent-exec result: " + "; ".join(validation.errors))

    try:
        _exclusive_write(
            run_dir / "meta.json",
            (json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    except OSError:
        pass
    try:
        gc_agent_exec(state_root=root, dry_run=False, protected_run_id=run_id)
    except OSError:
        pass
    return AgentExecOutcome(result, presentation, process_exit_code)


def read_agent_exec_meta(run_id: str, *, state_root: Path | None = None) -> dict[str, Any]:
    run_dir = _resolve_run_directory(state_root or default_agent_exec_state_root(), run_id)
    path = run_dir / "meta.json"
    if path.is_symlink():
        raise InvalidInputError("Refusing a symlinked agent execution metadata file.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInputError(
            f"Agent execution metadata is unavailable for {run_id}.",
            details={"run_id": run_id},
        ) from exc
    validation = validate_agent_exec_result(payload)
    if not validation.ok:
        raise InvalidInputError(
            f"Agent execution metadata is invalid for {run_id}.",
            details={"run_id": run_id, "errors": list(validation.errors)},
        )
    return payload


def read_agent_exec_diagnostic(
    run_id: str,
    *,
    tail_lines: int | None = None,
    state_root: Path | None = None,
) -> str:
    if tail_lines is not None and not 1 <= tail_lines <= FAIL_MAX_LINES:
        raise InvalidInputError(f"--tail must be between 1 and {FAIL_MAX_LINES}.")
    run_dir = _resolve_run_directory(state_root or default_agent_exec_state_root(), run_id)
    path = run_dir / "diagnostic.redacted.log"
    if path.is_symlink():
        raise InvalidInputError("Refusing a symlinked agent execution diagnostic.")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidInputError(
            f"No retained diagnostic is available for {run_id}.",
            details={"run_id": run_id},
        ) from exc
    lines = text.splitlines()
    if tail_lines is not None:
        lines = lines[-tail_lines:]
    bounded, _ = _bound_lines(lines, max_lines=FAIL_MAX_LINES, max_bytes=FAIL_MAX_BYTES)
    return bounded


def gc_agent_exec(
    *,
    state_root: Path | None = None,
    dry_run: bool,
    now_timestamp: float | None = None,
    retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    total_limit_bytes: int = DEFAULT_TOTAL_RETENTION_BYTES,
    protected_run_id: str | None = None,
) -> dict[str, Any]:
    root = (state_root or default_agent_exec_state_root()).expanduser()
    if root.is_symlink():
        raise InvalidInputError("Refusing a symlinked agent execution state root.")
    if not root.exists():
        return _gc_payload(dry_run=dry_run, candidates=[], removed=[], unsafe=[], byte_count=0)
    now = now_timestamp if now_timestamp is not None else datetime.now(timezone.utc).timestamp()
    records: list[tuple[float, str, Path, int, bool]] = []
    try:
        date_directories = sorted(root.iterdir())
    except OSError as exc:
        raise InvalidInputError("Could not inspect the agent execution state directory.") from exc
    for date_dir in date_directories:
        if date_dir.is_symlink() or not date_dir.is_dir():
            continue
        try:
            run_directories = sorted(date_dir.iterdir())
        except OSError:
            continue
        for run_dir in run_directories:
            if run_dir.is_symlink() or not run_dir.is_dir() or not RUN_ID_PATTERN.fullmatch(run_dir.name):
                continue
            try:
                size, safe = _run_directory_size(run_dir)
                modified = run_dir.stat().st_mtime
            except OSError:
                records.append((now, run_dir.name, run_dir, 0, False))
                continue
            records.append((modified, run_dir.name, run_dir, size, safe))

    total_bytes = sum(record[3] for record in records)
    selected: list[tuple[float, str, Path, int, bool]] = []
    selected_ids: set[str] = set()
    for record in sorted(records):
        modified, run_id, _path, _size, _safe = record
        if run_id == protected_run_id:
            continue
        if now - modified >= retention_seconds:
            selected.append(record)
            selected_ids.add(run_id)

    remaining = total_bytes - sum(record[3] for record in selected)
    if remaining > total_limit_bytes:
        for record in sorted(records):
            run_id = record[1]
            if run_id == protected_run_id or run_id in selected_ids:
                continue
            selected.append(record)
            selected_ids.add(run_id)
            remaining -= record[3]
            if remaining <= total_limit_bytes:
                break

    removed: list[str] = []
    unsafe: list[str] = []
    for _modified, run_id, run_dir, _size, safe in selected:
        if not safe:
            unsafe.append(run_id)
            continue
        if not dry_run:
            try:
                _delete_run_directory(run_dir)
            except OSError:
                unsafe.append(run_id)
                continue
            removed.append(run_id)
    candidates = [record[1] for record in selected]
    bytes_reclaimable = sum(record[3] for record in selected if record[4])
    return _gc_payload(
        dry_run=dry_run,
        candidates=candidates,
        removed=removed,
        unsafe=unsafe,
        byte_count=bytes_reclaimable,
    )


def render_agent_exec_human(result: dict[str, Any], diagnostic_text: str = "") -> str:
    raw_bytes = result["raw"]["stdout_bytes"] + result["raw"]["stderr_bytes"]
    duration = result["duration_ms"] / 1000
    if result["status"] == "PASS":
        line = (
            f"PASS run={result['run_id']} exit=0 duration={duration:.3f}s "
            f"raw={raw_bytes}B exposed=1L"
        )
        bounded, _ = _bound_lines([line], max_lines=PASS_MAX_LINES, max_bytes=PASS_MAX_BYTES)
        return bounded

    exit_label = result["exit_code"] if result["exit_code"] is not None else "none"
    lines = [
        f"{result['status']} run={result['run_id']} exit={exit_label} duration={duration:.3f}s"
    ]
    if diagnostic_text:
        lines.extend(diagnostic_text.splitlines())
    diagnostics = result["diagnostics"]
    lines.append(
        "diagnostics="
        f"{diagnostics['line_count']}L strategy={diagnostics['strategy']} "
        f"truncated={str(diagnostics['truncated']).lower()}"
    )
    if diagnostics["available"]:
        lines.append(f"inspect: pcl exec show {result['run_id']} --errors")
    bounded, _ = _bound_lines(lines, max_lines=FAIL_MAX_LINES, max_bytes=FAIL_MAX_BYTES)
    return bounded


def _compile_redaction_patterns(patterns: Iterable[str]) -> tuple[Pattern[str], ...]:
    compiled: list[Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise InvalidInputError(
                "Invalid --redact-pattern regular expression.",
                details={"pattern": pattern},
            ) from exc
    return tuple(compiled)


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"AX-{stamp}-{secrets.token_hex(6)}"


def _prepare_state_root(root: Path) -> Path:
    expanded = root.expanduser()
    if expanded.is_symlink():
        raise InvalidInputError("Refusing a symlinked agent execution state root.")
    try:
        expanded.mkdir(parents=True, mode=0o700, exist_ok=True)
        if os.name == "posix":
            expanded.chmod(0o700)
    except OSError as exc:
        raise InvalidInputError(
            "Could not create the local agent execution state directory.",
            details={"state_directory_available": False},
        ) from exc
    return expanded


def _create_run_directory(root: Path, run_id: str) -> Path:
    date_key = f"{run_id[3:7]}-{run_id[7:9]}-{run_id[9:11]}"
    date_dir = root / date_key
    if date_dir.is_symlink():
        raise InvalidInputError("Refusing a symlinked agent execution date directory.")
    try:
        date_dir.mkdir(mode=0o700, exist_ok=True)
        if os.name == "posix":
            date_dir.chmod(0o700)
        run_dir = date_dir / run_id
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise InvalidInputError("Agent execution run id collision.") from exc
    except OSError as exc:
        raise InvalidInputError("Could not create the local agent execution run directory.") from exc
    return run_dir


def _resolve_run_directory(root: Path, run_id: str) -> Path:
    expanded = root.expanduser()
    if expanded.is_symlink():
        raise InvalidInputError("Refusing a symlinked agent execution state root.")
    match = RUN_ID_PATTERN.fullmatch(run_id)
    if match is None:
        raise InvalidInputError("Invalid agent execution run id.", details={"run_id": run_id})
    date_digits = match.group(1)
    run_dir = expanded / (
        f"{date_digits[:4]}-{date_digits[4:6]}-{date_digits[6:8]}"
    ) / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise InvalidInputError(
            f"Agent execution run {run_id} was not found.", details={"run_id": run_id}
        )
    return run_dir


def _exclusive_write(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written < 1:
                raise OSError("short write while persisting agent execution state")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name == "posix":
        path.chmod(0o600)


def _redact_argv(
    argv: list[str],
    patterns: tuple[Pattern[str], ...],
    *,
    cwd: Path,
) -> tuple[list[str], bool]:
    redacted: list[str] = []
    changed = False
    redact_next = False
    total_bytes = 0
    for index, item in enumerate(argv):
        if redact_next:
            value = REDACTED_ARGUMENT
            item_changed = True
            redact_next = False
        else:
            redacted_bytes, item_changed = redact_bytes(
                item.encode("utf-8"), additional_patterns=patterns
            )
            value = redacted_bytes.decode("utf-8", errors="replace")
            if SENSITIVE_OPTION_PATTERN.fullmatch(item):
                redact_next = True
        value, path_changed = _sanitize_argument(value, cwd=cwd, executable=index == 0)
        value, clipped = _clip_argument(value)
        encoded_size = len(value.encode("utf-8")) + (1 if redacted else 0)
        if total_bytes + encoded_size > MAX_COMMAND_TOTAL_BYTES:
            redacted.append(f"<omitted:{len(argv) - index}-args>")
            changed = True
            break
        redacted.append(value)
        total_bytes += encoded_size
        changed = changed or item_changed or path_changed or clipped
    return redacted, changed


def _sanitize_argument(value: str, *, cwd: Path, executable: bool) -> tuple[str, bool]:
    if os.path.isabs(value):
        if executable:
            return f"<executable:{Path(value).name}>", True
        return "<absolute-path>", True
    if "=" in value:
        key, candidate = value.split("=", 1)
        if os.path.isabs(candidate):
            return f"{key}=<absolute-path>", True
    sanitized, changed = _replace_known_paths(value, cwd=cwd)
    return sanitized, changed


def _clip_argument(value: str) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= MAX_COMMAND_ITEM_BYTES:
        return value, False
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    prefix = encoded[:200].decode("utf-8", errors="ignore")
    return f"{prefix}...<sha256:{digest}>", True


def _classify_execution(execution: dict[str, Any]) -> tuple[str, int | None, int]:
    if execution.get("timed_out"):
        return "TIMEOUT", None, 124
    if execution.get("failure_kind") == "spawn_error":
        code = 127 if execution.get("spawn_error_kind") == "not_found" else 126
        return "INFRA_ERROR", None, code
    exit_code = execution.get("exit_code")
    if exit_code == 0:
        return "PASS", None, 0
    if isinstance(exit_code, int) and exit_code < 0:
        signal_number = -exit_code
        return "INTERRUPTED", signal_number, 128 + signal_number
    if isinstance(exit_code, int):
        return "FAIL", None, exit_code
    return "INFRA_ERROR", None, 126


def _select_diagnostic(execution: dict[str, Any]) -> DiagnosticSelection:
    streams: list[tuple[str, list[str]]] = []
    binary_present = False
    for name in ("stderr", "stdout"):
        metadata = execution[name]
        lines, stream_binary = _stream_lines(metadata)
        binary_present = binary_present or stream_binary
        streams.append((name.upper(), lines))

    selected: list[str] = []
    seen: set[tuple[str, int]] = set()
    for stream_name, lines in streams:
        for index, line in enumerate(lines):
            if not ERROR_LINE_PATTERN.search(line):
                continue
            for context_index in range(max(0, index - 2), min(len(lines), index + 3)):
                key = (stream_name, context_index)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(_diagnostic_line(stream_name, lines[context_index]))
    if selected:
        text, truncated = _bound_lines(
            selected, max_lines=FAIL_MAX_LINES - 4, max_bytes=FAIL_MAX_BYTES - 1_024
        )
        return DiagnosticSelection(text, "error-block", truncated)

    stderr_lines = next((lines for name, lines in streams if name == "STDERR"), [])
    if stderr_lines:
        labeled = [
            _diagnostic_line("STDERR", line)
            for line in stderr_lines[-(FAIL_MAX_LINES - 4) :]
        ]
        text, truncated = _bound_lines(
            labeled, max_lines=FAIL_MAX_LINES - 4, max_bytes=FAIL_MAX_BYTES - 1_024
        )
        return DiagnosticSelection(text, "stderr-tail", truncated)

    combined: list[str] = []
    for stream_name, lines in streams:
        combined.extend(_diagnostic_line(stream_name, line) for line in lines[-50:])
    if combined:
        text, truncated = _bound_lines(
            combined[-(FAIL_MAX_LINES - 4) :],
            max_lines=FAIL_MAX_LINES - 4,
            max_bytes=FAIL_MAX_BYTES - 1_024,
        )
        return DiagnosticSelection(text, "combined-tail", truncated)
    if binary_present:
        return DiagnosticSelection(
            "Binary command output was omitted from text diagnostics.",
            "binary-omitted",
            bool(execution.get("output_truncated")),
        )
    return DiagnosticSelection("", "none", bool(execution.get("output_truncated")))


def _stream_lines(metadata: dict[str, Any]) -> tuple[list[str], bool]:
    lines: list[str] = []
    binary = bool(metadata.get("binary"))
    if not binary:
        try:
            lines.extend(Path(metadata["path"]).read_text(encoding="utf-8").splitlines())
        except OSError:
            pass
    tail = metadata.get("tail")
    if metadata.get("truncated") and isinstance(tail, dict) and tail.get("persisted"):
        tail_binary = bool(tail.get("binary"))
        binary = binary or tail_binary
        if not tail_binary and tail.get("path"):
            try:
                tail_lines = Path(str(tail["path"])).read_text(encoding="utf-8").splitlines()
            except OSError:
                tail_lines = []
            if tail_lines:
                lines.append("[... bounded output omitted ...]")
                lines.extend(tail_lines)
    return lines, binary


def _diagnostic_line(stream_name: str, line: str) -> str:
    encoded = line.encode("utf-8", errors="replace")
    if len(encoded) > MAX_DIAGNOSTIC_LINE_BYTES:
        digest = hashlib.sha256(encoded).hexdigest()[:12]
        head = encoded[:440].decode("utf-8", errors="ignore")
        tail = encoded[-440:].decode("utf-8", errors="ignore")
        line = f"{head}...<sha256:{digest}>...{tail}"
    return f"{stream_name} | {line}"


def _sanitize_diagnostic(selection: DiagnosticSelection, *, cwd: Path) -> DiagnosticSelection:
    text, changed = _replace_known_paths(selection.text, cwd=cwd)
    text, unix_changed = UNIX_ABSOLUTE_PATH_PATTERN.subn("<absolute-path>", text)
    text, windows_changed = WINDOWS_ABSOLUTE_PATH_PATTERN.subn("<absolute-path>", text)
    bounded, truncated = _bound_lines(
        text.splitlines(), max_lines=FAIL_MAX_LINES - 4, max_bytes=FAIL_MAX_BYTES - 1_024
    )
    return DiagnosticSelection(
        bounded,
        selection.strategy,
        selection.truncated or truncated,
        selection.redacted or changed or unix_changed > 0 or windows_changed > 0,
    )


def _replace_known_paths(value: str, *, cwd: Path) -> tuple[str, bool]:
    changed = False
    result = value
    replacements = [
        (str(cwd.resolve()), "<project-root>"),
        (str(Path.home().resolve()), "<home>"),
    ]
    for source, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        if len(source) <= 1 or source not in result:
            continue
        result = result.replace(source, replacement)
        changed = True
    return result, changed


def _compact_termination(value: object) -> dict[str, Any]:
    termination = value if isinstance(value, dict) else {}
    return {
        "requested": bool(termination.get("requested")),
        "method": str(termination.get("method") or ""),
        "escalated": bool(termination.get("escalated")),
        "group_state": str(termination.get("group_state") or "unknown"),
        "group_uncertain": bool(termination.get("group_uncertain")),
        "pipes_eof": bool(termination.get("pipes_eof")),
    }


def _stabilize_presentation(result: dict[str, Any], diagnostic_text: str) -> str:
    previous = ""
    for _ in range(4):
        presentation = render_agent_exec_human(result, diagnostic_text)
        result["exposed"] = {
            "lines": _line_count(presentation),
            "bytes": len(presentation.encode("utf-8")),
        }
        if presentation == previous:
            return presentation
        previous = presentation
    return previous


def _bound_lines(
    lines: Iterable[str], *, max_lines: int, max_bytes: int
) -> tuple[str, bool]:
    selected: list[str] = []
    byte_count = 0
    truncated = False
    for line in lines:
        if len(selected) >= max_lines:
            truncated = True
            break
        encoded = line.encode("utf-8", errors="replace")
        separator = 1 if selected else 0
        if byte_count + separator + len(encoded) > max_bytes:
            remaining = max_bytes - byte_count - separator
            if remaining > 0:
                clipped = encoded[:remaining].decode("utf-8", errors="ignore")
                if clipped:
                    selected.append(clipped)
            truncated = True
            break
        selected.append(line)
        byte_count += separator + len(encoded)
    return "\n".join(selected), truncated


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _run_directory_size(run_dir: Path) -> tuple[int, bool]:
    total = 0
    safe = True
    for child in run_dir.iterdir():
        if child.name not in EXPECTED_RUN_FILES or child.is_symlink() or not child.is_file():
            safe = False
            continue
        total += child.stat().st_size
    return total, safe


def _delete_run_directory(run_dir: Path) -> None:
    for child in run_dir.iterdir():
        if child.name not in EXPECTED_RUN_FILES or child.is_symlink() or not child.is_file():
            raise OSError("unsafe agent execution run directory")
        child.unlink()
    parent = run_dir.parent
    run_dir.rmdir()
    try:
        parent.rmdir()
    except OSError:
        pass


def _gc_payload(
    *,
    dry_run: bool,
    candidates: list[str],
    removed: list[str],
    unsafe: list[str],
    byte_count: int,
) -> dict[str, Any]:
    return {
        "schema": "agent-exec-gc/v1",
        "ok": not unsafe,
        "dry_run": dry_run,
        "candidate_run_ids": candidates,
        "removed_run_ids": removed,
        "unsafe_run_ids": unsafe,
        "reclaimable_bytes": byte_count,
    }
