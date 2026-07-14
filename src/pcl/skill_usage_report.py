from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
from json import JSONDecodeError
import mmap
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterable

from .errors import InvalidInputError


SKILL_USAGE_REPORT_CONTRACT_VERSION = "skill-usage-report/v1"
SKILL_USAGE_SOURCES = ("codex", "claude", "cockpit")
DEFAULT_WINDOW_DAYS = 30

_SKILL_PATH_RE = re.compile(r"project-control-loop/SKILL\.md", re.IGNORECASE)
_SHELL_READ_RE = re.compile(
    r"(?:^|[;&|\n])\s*(?:[A-Z_][A-Z0-9_]*=[^\s]+\s+)*(?:sed|cat|head|tail|bat|less)\b",
    re.IGNORECASE,
)
_COCKPIT_SKILL_RE = re.compile(
    r"\[skill:project-control-loop(?:@[^\]]+)?\]|\$project-control-loop\b",
    re.IGNORECASE,
)
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON_RE = re.compile(r"^python(?:3(?:\.\d+)?)?$", re.IGNORECASE)
_COMMAND_ERROR_RE = re.compile(
    r"script failed with code [1-9]\d*|process exited with code [1-9]\d*|"
    r"exit code [1-9]\d*|[\"']exit_code[\"']\s*:\s*[1-9]\d*",
    re.IGNORECASE,
)
_FRICTION_PATTERNS = {
    "finish_checks_not_configured": re.compile(
        r"finish_checks_not_configured|no (?:enabled )?finish checks are configured",
        re.IGNORECASE,
    ),
    "timeout": re.compile(r"\btimed out\b|\btimeout\b", re.IGNORECASE),
    "guarded_execution_blocked": re.compile(
        r"guarded_execution_blocked|blocked by guarded|guarded executor.{0,60}(?:reject|block)",
        re.IGNORECASE | re.DOTALL,
    ),
    "completed_with_risk": re.compile(r"COMPLETED_WITH_RISK", re.IGNORECASE),
}
_OUTPUT_SIGNAL_MARKERS = (
    "finish_checks",
    "finish checks",
    "timeout",
    "timed out",
    "guarded",
    "completed_with_risk",
    "exit code",
    "exit_code",
    "script failed",
    "process exited",
)
_CODEX_LINE_NEEDLES = (
    b"session_meta",
    b"tools.exec_command",
    b'"name":"exec_command"',
    b'"name": "exec_command"',
    b"tool_call_output",
    b"function_call_output",
)
_CLAUDE_LINE_NEEDLES = (
    b"project-control-loop",
    b"tool_result",
)
_COCKPIT_LINE_NEEDLES = (b"project-control-loop",)
_CODEX_SKILL_RG_PATTERN = (
    r'tools\.exec_command.*project-control-loop/SKILL\.md|'
    r'"name"\s*:\s*"exec_command".*project-control-loop/SKILL\.md'
)
_CODEX_SELECTED_FIXED_PATTERNS = (
    "project-control-loop/SKILL.md",
    " -m pcl",
    "pcl ",
    "finish_checks_not_configured",
    "No enabled finish checks are configured",
    "No finish checks are configured",
    "timed out",
    "guarded_execution_blocked",
    "COMPLETED_WITH_RISK",
    "Exit code ",
    "exit code ",
    '"exit_code":',
    "'exit_code':",
    "Script failed with code",
    "Process exited with code",
)
_FRICTION_ORDER = (
    "finish_checks_not_configured",
    "guarded_execution_blocked",
    "timeout",
    "completed_with_risk",
    "command_error",
    "help_probe",
    "repeated_command",
)
_RETRY_TRIGGER_CODES = {
    "command_error",
    "guarded_execution_blocked",
    "timeout",
}
_KNOWN_SUBCOMMANDS = {
    "agent": {"command"},
    "audit": {"check", "flush", "rebuild-jsonl", "repair"},
    "baseline": {"compare", "record"},
    "brief": {"add", "approve", "review", "show"},
    "checkpoint": {"record", "status"},
    "code": {"search"},
    "completion": {"evaluate"},
    "context": {"check", "pack"},
    "contract": {"validate"},
    "decision": {"list", "open", "read", "resolve", "waive"},
    "defect": {"close", "fix", "open", "start", "triage", "verify", "waive"},
    "escalation": {"cancel", "list", "open", "read", "resolve"},
    "eval": {"retrieval"},
    "evidence": {"add", "link", "list", "show", "supersede"},
    "export": {"csv"},
    "feature": {"add", "list", "read", "show", "status"},
    "goal": {"cancel", "close", "create", "list", "read", "show"},
    "index": {"build", "status"},
    "jobs": {"assign", "cancel", "complete", "fail", "lease", "list", "read", "reap"},
    "loop": {"cancel", "complete", "execute", "run", "status"},
    "migrate": {"apply", "status"},
    "policy": {"explain", "resolve"},
    "profile": {
        "authorize",
        "fixture-run",
        "ingest",
        "list",
        "prepare",
        "proposal",
        "show",
        "validate",
    },
    "repair": {"lifecycle"},
    "report": {"defect", "feature", "goal", "kpi", "run", "skill-usage", "validation"},
    "route": {"current", "override", "recommend"},
    "story": {"approve", "draft", "list", "read", "review", "waive"},
    "task": {"create", "depend", "list", "read", "status"},
    "test": {"block", "fail", "link", "list", "missing", "pass", "plan", "read", "waive"},
    "update": {"check", "command"},
    "verification": {"feedback", "list", "read", "record", "stats"},
    "workflow": {"guard", "list", "proposal", "proposals", "propose", "sandbox", "show", "verify"},
}
_DIRECT_COMMANDS = {
    "doctor",
    "finish",
    "guide",
    "impact",
    "ingest-agent-run",
    "init",
    "next",
    "prompt",
    "receipt",
    "render",
    "resume",
    "start",
    "status",
    "validate",
    "version",
}


@dataclass
class _SessionObservation:
    source: str
    key: str
    workspace: str | None = None
    skill_seen_any: bool = False
    skill_seen_in_window: bool = False
    commands: Counter[str] = field(default_factory=Counter)
    help_probes: int = 0
    help_probe_commands: Counter[str] = field(default_factory=Counter)
    friction: Counter[str] = field(default_factory=Counter)
    friction_commands: dict[str, Counter[str]] = field(default_factory=dict)
    pcl_call_ids: set[str] = field(default_factory=set)
    pcl_call_commands: dict[str, Counter[str]] = field(default_factory=dict)
    pending_retry_commands: Counter[str] = field(default_factory=Counter)

    @property
    def included(self) -> bool:
        return self.skill_seen_any and (
            self.skill_seen_in_window or bool(self.commands) or bool(self.friction)
        )


@dataclass
class _SourceScan:
    source: str
    available: bool
    files_scanned: int = 0
    parse_errors: int = 0
    sessions: dict[str, _SessionObservation] = field(default_factory=dict)
    cockpit_tasks: set[str] = field(default_factory=set)


def report_skill_usage(
    *,
    since: str | None = None,
    until: str | None = None,
    sources: Iterable[str] | None = None,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
    cockpit_root: str | Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    window = _normalize_window(since=since, until=until, today=today)
    selected = _normalize_sources(sources)
    roots = default_skill_usage_roots(
        codex_root=codex_root,
        claude_root=claude_root,
        cockpit_root=cockpit_root,
    )

    scans: dict[str, _SourceScan] = {}
    for source in selected:
        if source == "codex":
            scans[source] = _scan_codex(roots[source], window=window)
        elif source == "claude":
            scans[source] = _scan_claude(roots[source], window=window)
        else:
            scans[source] = _scan_cockpit(roots[source], window=window)

    agent_sessions = [
        session
        for source in ("codex", "claude")
        if source in scans
        for session in scans[source].sessions.values()
        if session.included
    ]
    commands = Counter[str]()
    command_sessions: dict[str, int] = Counter()
    friction = Counter[str]()
    friction_sessions: dict[str, int] = Counter()
    friction_commands: dict[str, Counter[str]] = {}
    friction_command_sessions: dict[str, Counter[str]] = {}
    workspaces: set[str] = set()
    sessions_with_commands = 0

    for session in agent_sessions:
        commands.update(session.commands)
        for command in session.commands:
            command_sessions[command] += 1
        if session.commands:
            sessions_with_commands += 1
        if session.workspace:
            workspaces.add(session.workspace)
        session_friction = Counter(session.friction)
        session_friction_commands = {
            code: Counter(command_counts)
            for code, command_counts in session.friction_commands.items()
        }
        if session.help_probes:
            session_friction["help_probe"] += session.help_probes
            session_friction_commands["help_probe"] = Counter(
                session.help_probe_commands
            )
        friction.update(session_friction)
        for code in session_friction:
            friction_sessions[code] += 1
        for code, command_counts in session_friction_commands.items():
            friction_commands.setdefault(code, Counter()).update(command_counts)
            attributed_sessions = friction_command_sessions.setdefault(code, Counter())
            for command in command_counts:
                attributed_sessions[command] += 1

    cockpit_tasks = len(scans.get("cockpit", _SourceScan("cockpit", False)).cockpit_tasks)
    source_payloads = {
        source: _source_payload(scans[source])
        for source in SKILL_USAGE_SOURCES
        if source in scans
    }
    friction_command_payloads = {
        code: [
            {
                "command": command,
                "occurrence_count": count,
                "session_count": friction_command_sessions.get(code, Counter())[command],
            }
            for command, count in sorted(
                command_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]
        for code, command_counts in friction_commands.items()
    }
    friction_payload = []
    for code in _FRICTION_ORDER:
        if not friction[code]:
            continue
        friction_payload.append(
            {
                "code": code,
                "occurrence_count": friction[code],
                "session_count": friction_sessions[code],
                "classification": "observed_signal_not_proven_product_defect",
                "commands": friction_command_payloads.get(code, []),
            }
        )
    report = {
        "ok": True,
        "contract_version": SKILL_USAGE_REPORT_CONTRACT_VERSION,
        "window": window,
        "summary": {
            "agent_skill_sessions": len(agent_sessions),
            "agent_sessions_with_pcl_commands": sessions_with_commands,
            "pcl_commands_detected": sum(commands.values()),
            "distinct_workspaces": len(workspaces),
            "cockpit_control_plane_tasks": cockpit_tasks,
        },
        "sources": source_payloads,
        "commands": [
            {
                "command": command,
                "count": count,
                "session_count": command_sessions[command],
            }
            for command, count in sorted(commands.items(), key=lambda item: (-item[1], item[0]))
        ],
        "friction": friction_payload,
        "improvement_candidates": _improvement_candidates(
            friction=friction,
            friction_sessions=friction_sessions,
            friction_commands=friction_command_payloads,
        ),
        "privacy": {
            "raw_content_retained": False,
            "command_arguments_retained": False,
            "session_identifiers_retained": False,
            "workspace_paths_retained": False,
            "external_transmission": False,
        },
        "limitations": [
            "Signals are inferred from supported local JSONL shapes and may undercount unknown adapters.",
            "Command errors and repeated commands are observations, not proof of a product defect.",
            "Cockpit task signals are reported separately to avoid double-counting mediated agent runs.",
        ],
    }
    return report


def render_skill_usage_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Local PCL Skill usage report",
        "",
        f"Window: {report['window']['since']} through {report['window']['until']}",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Agent Skill sessions | {summary['agent_skill_sessions']} |",
        f"| Sessions with pcl commands | {summary['agent_sessions_with_pcl_commands']} |",
        f"| pcl commands detected | {summary['pcl_commands_detected']} |",
        f"| Distinct workspaces | {summary['distinct_workspaces']} |",
        f"| Cockpit control-plane tasks | {summary['cockpit_control_plane_tasks']} |",
        "",
        "## Sources",
        "",
        "| Source | Status | Files | Parse errors | Skill sessions/tasks |",
        "|---|---|---:|---:|---:|",
    ]
    for source, payload in report["sources"].items():
        signal_count = payload.get("skill_sessions", payload.get("control_plane_tasks", 0))
        lines.append(
            f"| {source} | {payload['status']} | {payload['files_scanned']} | "
            f"{payload['parse_errors']} | {signal_count} |"
        )

    lines.extend(["", "## Normalized commands", ""])
    if report["commands"]:
        lines.extend(["| Command | Count | Sessions |", "|---|---:|---:|"])
        for item in report["commands"]:
            lines.append(
                f"| `{item['command']}` | {item['count']} | {item['session_count']} |"
            )
    else:
        lines.append("No normalized pcl command was detected in the selected window.")

    lines.extend(["", "## Friction signals", ""])
    if report["friction"]:
        lines.extend(
            [
                "| Signal | Occurrences | Sessions | Leading commands |",
                "|---|---:|---:|---|",
            ]
        )
        for item in report["friction"]:
            leading = ", ".join(
                f"`{command['command']}` {command['occurrence_count']}"
                for command in item["commands"][:3]
            )
            lines.append(
                f"| `{item['code']}` | {item['occurrence_count']} | "
                f"{item['session_count']} | {leading or '—'} |"
            )
    else:
        lines.append("No supported friction signal was detected in the selected window.")

    lines.extend(["", "## Advisory improvement candidates", ""])
    if report["improvement_candidates"]:
        for item in report["improvement_candidates"]:
            leading = item["evidence"].get("leading_command")
            leading_text = f", leading command `{leading['command']}`" if leading else ""
            lines.append(
                f"- **{item['priority']} `{item['code']}`** — {item['recommendation']} "
                f"({item['evidence']['session_count']} sessions{leading_text})"
            )
    else:
        lines.append("No improvement candidate has enough observed evidence in this window.")

    lines.extend(
        [
            "",
            "## Privacy boundary",
            "",
            "The report retains no raw conversation, tool output, command arguments, session IDs, "
            "workspace paths, or external data. Candidates are advisory until reproduced as tests.",
            "",
        ]
    )
    return "\n".join(lines)


def default_skill_usage_roots(
    *,
    codex_root: str | Path | None = None,
    claude_root: str | Path | None = None,
    cockpit_root: str | Path | None = None,
) -> dict[str, Path]:
    home = Path.home()
    return {
        "codex": Path(codex_root).expanduser()
        if codex_root is not None
        else home / ".codex" / "sessions",
        "claude": Path(claude_root).expanduser()
        if claude_root is not None
        else home / ".claude" / "projects",
        "cockpit": Path(cockpit_root).expanduser()
        if cockpit_root is not None
        else home / ".agi-tools" / "data" / "cockpit" / "task-reports",
    }


def write_skill_usage_report(
    path: str | Path,
    content: str,
    *,
    forbidden_roots: Iterable[str | Path] = (),
    forbidden_paths: Iterable[str | Path] = (),
) -> Path:
    destination = Path(path).expanduser()
    resolved_destination = destination.resolve()
    if any(
        resolved_destination.is_relative_to(Path(root).expanduser().resolve())
        for root in forbidden_roots
    ) or any(
        resolved_destination == Path(item).expanduser().resolve() for item in forbidden_paths
    ):
        raise InvalidInputError(
            "--output must not overwrite a scanned log root or authoritative PCL state.",
            details={"output_rejected": True},
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_value = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temp = Path(temp_value)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, destination)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return destination


def serialized_skill_usage_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n"


def _normalize_window(
    *,
    since: str | None,
    until: str | None,
    today: date | None,
) -> dict[str, str]:
    resolved_today = today or date.today()
    since_date = _parse_date(since, flag="--since") if since else resolved_today - timedelta(
        days=DEFAULT_WINDOW_DAYS
    )
    until_date = _parse_date(until, flag="--until") if until else resolved_today
    if since_date > until_date:
        raise InvalidInputError(
            "--since must be on or before --until.",
            details={"since": since_date.isoformat(), "until": until_date.isoformat()},
        )
    return {"since": since_date.isoformat(), "until": until_date.isoformat()}


def _parse_date(value: str, *, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInputError(
            f"{flag} must be an ISO date in YYYY-MM-DD format.",
            details={flag.removeprefix("--"): value},
        ) from exc


def _normalize_sources(sources: Iterable[str] | None) -> tuple[str, ...]:
    requested = tuple(sources or SKILL_USAGE_SOURCES)
    unknown = sorted({source for source in requested if source not in SKILL_USAGE_SOURCES})
    if unknown:
        raise InvalidInputError(
            "Unknown skill-usage report source.",
            details={"unknown_sources": unknown, "allowed_sources": list(SKILL_USAGE_SOURCES)},
        )
    selected = set(requested)
    return tuple(source for source in SKILL_USAGE_SOURCES if source in selected)


def _scan_codex(root: Path, *, window: dict[str, str]) -> _SourceScan:
    scan = _SourceScan(source="codex", available=root.is_dir())
    if not scan.available:
        return scan
    candidates = _candidate_files(root, since=window["since"])
    matched = _matching_codex_skill_files(candidates, root=root)
    scan.files_scanned = len(candidates)
    accelerated = _rg_rows_for_files(
        matched,
        fixed_patterns=_CODEX_SELECTED_FIXED_PATTERNS,
        scan=scan,
    )
    if accelerated is not None:
        by_path = {
            path.resolve(): _SessionObservation(source="codex", key=f"file:{index}")
            for index, path in enumerate(matched, start=1)
        }
        for path in matched:
            session = by_path[path.resolve()]
            metadata = _read_codex_session_meta(path)
            if metadata is not None:
                _consume_codex_row(session, row=metadata, path=path, window=window)
        for path, row in accelerated:
            session = by_path.get(path.resolve())
            if session is not None:
                _consume_codex_row(session, row=row, path=path, window=window)
        for session in by_path.values():
            _merge_session(scan.sessions, session)
        return scan
    for matched_index, path in enumerate(matched, start=1):
        default_key = f"file:{matched_index}"
        session = _SessionObservation(source="codex", key=default_key)
        for row in _read_selected_jsonl(
            path,
            scan=scan,
            needles=_CODEX_LINE_NEEDLES,
            relevant_line=_codex_line_relevant,
        ):
            _consume_codex_row(session, row=row, path=path, window=window)
        _merge_session(scan.sessions, session)
    return scan


def _scan_claude(root: Path, *, window: dict[str, str]) -> _SourceScan:
    scan = _SourceScan(source="claude", available=root.is_dir())
    if not scan.available:
        return scan
    candidates = _candidate_files(root, since=window["since"])
    matched = _matching_files(candidates, root=root, needle="project-control-loop")
    scan.files_scanned = len(candidates)
    for matched_index, path in enumerate(matched, start=1):
        session = _SessionObservation(source="claude", key=f"file:{matched_index}")
        for row in _read_selected_jsonl(
            path,
            scan=scan,
            needles=_CLAUDE_LINE_NEEDLES,
            relevant_line=_claude_line_relevant,
        ):
            identifier = row.get("sessionId") or row.get("session_id")
            if isinstance(identifier, str) and identifier:
                session.key = identifier
            cwd = row.get("cwd")
            if isinstance(cwd, str) and cwd:
                session.workspace = cwd
            in_window = _row_in_window(row, window=window, fallback=path)
            message = row.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), list):
                continue
            for item in message["content"]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    name = item.get("name")
                    tool_input = item.get("input")
                    if _claude_skill_signal(name, tool_input):
                        session.skill_seen_any = True
                        if in_window:
                            session.skill_seen_in_window = True
                    if name == "Bash" and in_window and isinstance(tool_input, dict):
                        shell_command = tool_input.get("command")
                        if isinstance(shell_command, str):
                            tool_id = item.get("id")
                            _record_pcl_call(
                                session,
                                [shell_command],
                                call_id=tool_id if isinstance(tool_id, str) else None,
                            )
                elif item.get("type") == "tool_result" and in_window:
                    tool_use_id = item.get("tool_use_id")
                    if not isinstance(tool_use_id, str) or tool_use_id not in session.pcl_call_ids:
                        continue
                    error_state = item.get("is_error")
                    _classify_output(
                        session,
                        item.get("content"),
                        call_id=tool_use_id,
                        is_error=error_state if isinstance(error_state, bool) else None,
                    )
        _merge_session(scan.sessions, session)
    return scan


def _scan_cockpit(root: Path, *, window: dict[str, str]) -> _SourceScan:
    scan = _SourceScan(source="cockpit", available=root.is_dir())
    if not scan.available:
        return scan
    candidates = _candidate_files(root, since=window["since"])
    matched = _matching_files(candidates, root=root, needle="project-control-loop")
    scan.files_scanned = len(candidates)
    for matched_index, path in enumerate(matched, start=1):
        for row in _read_selected_jsonl(
            path,
            scan=scan,
            needles=_COCKPIT_LINE_NEEDLES,
            relevant_line=_cockpit_line_relevant,
        ):
            if not _row_in_window(row, window=window, fallback=path, timestamp_key="createdAt"):
                continue
            message = row.get("message")
            if not isinstance(message, str) or not _COCKPIT_SKILL_RE.search(message):
                continue
            task_id = row.get("taskId")
            if not isinstance(task_id, str) or not task_id:
                task_id = f"file:{matched_index}"
            scan.cockpit_tasks.add(task_id)
    return scan


def _candidate_files(root: Path, *, since: str) -> list[Path]:
    since_timestamp = datetime.combine(
        date.fromisoformat(since), datetime.min.time(), tzinfo=timezone.utc
    ).timestamp()
    candidates: list[Path] = []
    for path in root.rglob("*.jsonl"):
        try:
            if path.is_file() and path.stat().st_mtime >= since_timestamp:
                candidates.append(path)
        except OSError:
            continue
    return sorted(candidates)


def _matching_files(candidates: list[Path], *, root: Path, needle: str) -> list[Path]:
    ripgrep = shutil.which("rg")
    if ripgrep:
        try:
            completed = subprocess.run(
                [
                    ripgrep,
                    "--files-with-matches",
                    "--null",
                    "--fixed-strings",
                    "--glob",
                    "*.jsonl",
                    "--no-messages",
                    needle,
                    str(root),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode in {0, 1}:
            matched = {
                Path(os.fsdecode(value)).resolve()
                for value in completed.stdout.split(b"\0")
                if value
            }
            return [path for path in candidates if path.resolve() in matched]
    encoded = needle.encode("utf-8")
    return [path for path in candidates if _file_contains_any(path, (encoded,))]


def _matching_codex_skill_files(candidates: list[Path], *, root: Path) -> list[Path]:
    ripgrep = shutil.which("rg")
    candidate_set = {path.resolve() for path in candidates}
    if ripgrep:
        try:
            completed = subprocess.run(
                [
                    ripgrep,
                    "--json",
                    "--glob",
                    "*.jsonl",
                    "--no-messages",
                    _CODEX_SKILL_RG_PATTERN,
                    str(root),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode in {0, 1}:
            matched: set[Path] = set()
            for raw_event in completed.stdout.splitlines():
                try:
                    event = json.loads(raw_event)
                except JSONDecodeError:
                    continue
                if event.get("type") != "match" or not isinstance(event.get("data"), dict):
                    continue
                data = event["data"]
                path_value = data.get("path", {}).get("text")
                line_value = data.get("lines", {}).get("text")
                if not isinstance(path_value, str) or not isinstance(line_value, str):
                    continue
                try:
                    row = json.loads(line_value)
                except JSONDecodeError:
                    continue
                payload = row.get("payload") if isinstance(row, dict) else None
                if (
                    not isinstance(payload, dict)
                    or row.get("type") != "response_item"
                    or payload.get("type") not in {"custom_tool_call", "function_call"}
                ):
                    continue
                if any(_is_skill_read_command(command) for command in _codex_shell_commands(payload)):
                    resolved = Path(path_value).resolve()
                    if resolved in candidate_set:
                        matched.add(resolved)
            return [path for path in candidates if path.resolve() in matched]
    return _matching_files(
        candidates,
        root=root,
        needle="project-control-loop/SKILL.md",
    )


def _rg_rows_for_files(
    paths: list[Path],
    *,
    fixed_patterns: tuple[str, ...],
    scan: _SourceScan,
) -> Iterable[tuple[Path, dict[str, Any]]] | None:
    if not paths:
        return iter(())
    ripgrep = shutil.which("rg")
    if not ripgrep:
        return None
    argv = [ripgrep, "--json", "--no-messages", "--fixed-strings"]
    for pattern in fixed_patterns:
        argv.extend(["-e", pattern])
    argv.extend(str(path) for path in paths)
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None

    def iter_rows() -> Iterable[tuple[Path, dict[str, Any]]]:
        assert process.stdout is not None
        try:
            for raw_event in process.stdout:
                try:
                    event = json.loads(raw_event)
                except JSONDecodeError:
                    continue
                if event.get("type") != "match" or not isinstance(
                    event.get("data"), dict
                ):
                    continue
                data = event["data"]
                path_value = data.get("path", {}).get("text")
                line_value = data.get("lines", {}).get("text")
                if not isinstance(path_value, str) or not isinstance(line_value, str):
                    continue
                stripped = line_value.strip()
                if not stripped.startswith("{") or not stripped.endswith("}"):
                    scan.parse_errors += 1
                    continue
                try:
                    row = json.loads(stripped)
                except JSONDecodeError:
                    scan.parse_errors += 1
                    continue
                if isinstance(row, dict):
                    yield Path(path_value), row
                else:
                    scan.parse_errors += 1
        finally:
            process.stdout.close()
            return_code = process.wait()
            if return_code not in {0, 1}:
                scan.parse_errors += 1

    return iter_rows()


def _read_codex_session_meta(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as stream:
            for _ in range(32):
                raw = stream.readline()
                if not raw:
                    break
                if b"session_meta" not in raw:
                    continue
                try:
                    row = json.loads(raw)
                except JSONDecodeError:
                    return None
                if isinstance(row, dict) and row.get("type") == "session_meta":
                    return row
    except OSError:
        return None
    return None


def _consume_codex_row(
    session: _SessionObservation,
    *,
    row: dict[str, Any],
    path: Path,
    window: dict[str, str],
) -> None:
    if row.get("type") == "session_meta" and isinstance(row.get("payload"), dict):
        payload = row["payload"]
        identifier = payload.get("id") or payload.get("session_id")
        if isinstance(identifier, str) and identifier:
            session.key = identifier
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and cwd:
            session.workspace = cwd
        return
    if row.get("type") != "response_item" or not isinstance(row.get("payload"), dict):
        return
    payload = row["payload"]
    in_window = _row_in_window(row, window=window, fallback=path)
    payload_type = payload.get("type")
    if payload_type in {"custom_tool_call", "function_call"}:
        shell_commands = _codex_shell_commands(payload)
        for shell_command in shell_commands:
            if _is_skill_read_command(shell_command):
                session.skill_seen_any = True
                if in_window:
                    session.skill_seen_in_window = True
        call_id = payload.get("call_id")
        if in_window:
            _record_pcl_call(
                session,
                shell_commands,
                call_id=call_id if isinstance(call_id, str) else None,
            )
    elif payload_type in {"custom_tool_call_output", "function_call_output"} and in_window:
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id in session.pcl_call_ids:
            _classify_output(session, payload.get("output"), call_id=call_id)


def _file_contains_any(path: Path, needles: tuple[bytes, ...]) -> bool:
    try:
        with path.open("rb") as stream:
            if os.fstat(stream.fileno()).st_size == 0:
                return False
            with mmap.mmap(stream.fileno(), length=0, access=mmap.ACCESS_READ) as mapped:
                return any(mapped.find(needle) >= 0 for needle in needles)
    except (OSError, ValueError):
        return False


def _read_selected_jsonl(
    path: Path,
    *,
    scan: _SourceScan,
    needles: tuple[bytes, ...],
    relevant_line: Callable[[str], bool],
) -> Iterable[dict[str, Any]]:
    try:
        with path.open("rb") as stream:
            if os.fstat(stream.fileno()).st_size == 0:
                return
            with mmap.mmap(stream.fileno(), length=0, access=mmap.ACCESS_READ) as mapped:
                starts: set[int] = set()
                for needle in needles:
                    position = 0
                    while True:
                        position = mapped.find(needle, position)
                        if position < 0:
                            break
                        starts.add(mapped.rfind(b"\n", 0, position) + 1)
                        position += len(needle)
                for start in sorted(starts):
                    end = mapped.find(b"\n", start)
                    if end < 0:
                        end = len(mapped)
                    raw = bytes(mapped[start:end]).strip()
                    if not raw:
                        continue
                    if not raw.startswith(b"{") or not raw.endswith(b"}"):
                        scan.parse_errors += 1
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    if not relevant_line(text):
                        continue
                    try:
                        row = json.loads(raw)
                    except JSONDecodeError:
                        scan.parse_errors += 1
                        continue
                    if isinstance(row, dict):
                        yield row
                    else:
                        scan.parse_errors += 1
    except (OSError, ValueError):
        scan.parse_errors += 1


def _codex_line_relevant(line: str) -> bool:
    lowered = line.lower()
    if "session_meta" in lowered:
        return True
    if any(marker in lowered for marker in _OUTPUT_SIGNAL_MARKERS):
        return "tool_call_output" in lowered or "function_call_output" in lowered
    return (
        ("custom_tool_call" in lowered or "function_call" in lowered)
        and ("project-control-loop" in lowered or "pcl" in lowered)
    )


def _claude_line_relevant(line: str) -> bool:
    lowered = line.lower()
    if "tool_use" in lowered and ("project-control-loop" in lowered or "pcl" in lowered):
        return True
    return "tool_result" in lowered and any(
        marker in lowered for marker in _OUTPUT_SIGNAL_MARKERS
    )


def _cockpit_line_relevant(line: str) -> bool:
    return "project-control-loop" in line.lower()


def _row_in_window(
    row: dict[str, Any],
    *,
    window: dict[str, str],
    fallback: Path,
    timestamp_key: str = "timestamp",
) -> bool:
    value = row.get(timestamp_key)
    observed = _timestamp_date(value)
    if observed is None:
        try:
            observed = datetime.fromtimestamp(fallback.stat().st_mtime, tz=timezone.utc).date()
        except OSError:
            return False
    return date.fromisoformat(window["since"]) <= observed <= date.fromisoformat(window["until"])


def _timestamp_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def _codex_shell_commands(payload: dict[str, Any]) -> list[str]:
    name = payload.get("name")
    if name == "exec":
        tool_input = payload.get("input")
        return _commands_from_exec_javascript(tool_input) if isinstance(tool_input, str) else []
    if name == "exec_command":
        arguments = payload.get("arguments")
        if not isinstance(arguments, str):
            return []
        try:
            parsed = json.loads(arguments)
        except JSONDecodeError:
            return []
        command = parsed.get("cmd") if isinstance(parsed, dict) else None
        return [command] if isinstance(command, str) else []
    return []


def _commands_from_exec_javascript(value: str) -> list[str]:
    commands: list[str] = []
    pattern = re.compile(
        r"exec_command\(\s*(\{(?:[^{}\"]|\"(?:\\.|[^\"])*\")*\})\s*\)",
        re.DOTALL,
    )
    for match in pattern.finditer(value):
        try:
            parsed = json.loads(match.group(1))
        except JSONDecodeError:
            continue
        command = parsed.get("cmd") if isinstance(parsed, dict) else None
        if isinstance(command, str):
            commands.append(command)
    return commands


def _is_skill_read_command(command: str) -> bool:
    return bool(_SKILL_PATH_RE.search(command) and _SHELL_READ_RE.search(command))


def _claude_skill_signal(name: Any, tool_input: Any) -> bool:
    if name == "Skill" and isinstance(tool_input, dict):
        skill = tool_input.get("skill")
        return isinstance(skill, str) and skill == "project-control-loop"
    if name == "Read" and isinstance(tool_input, dict):
        file_path = tool_input.get("file_path")
        return isinstance(file_path, str) and bool(_SKILL_PATH_RE.search(file_path))
    return False


def _record_pcl_call(
    session: _SessionObservation,
    shell_commands: Iterable[str],
    *,
    call_id: str | None,
) -> int:
    normalized = [
        item
        for shell_command in shell_commands
        for item in _normalized_pcl_commands(shell_command)
    ]
    if not normalized:
        return 0

    current_commands = Counter(command for command, _help_probe in normalized)
    if session.pending_retry_commands:
        for command in current_commands.keys() & session.pending_retry_commands.keys():
            repeat_count = min(
                current_commands[command], session.pending_retry_commands[command]
            )
            if repeat_count:
                session.friction["repeated_command"] += repeat_count
                _add_friction_command(
                    session,
                    code="repeated_command",
                    command=command,
                    count=repeat_count,
                )
        session.pending_retry_commands.clear()

    session.commands.update(current_commands)
    for command, help_probe in normalized:
        if help_probe:
            session.help_probes += 1
            session.help_probe_commands[command] += 1

    if call_id is not None:
        session.pcl_call_ids.add(call_id)
        session.pcl_call_commands.setdefault(call_id, Counter()).update(current_commands)
    return len(normalized)


def _normalized_pcl_commands(shell_command: str) -> list[tuple[str, bool]]:
    try:
        lexer = shlex.shlex(shell_command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    normalized: list[tuple[str, bool]] = []
    for segment in segments:
        invocation = _normalize_pcl_segment(segment)
        if invocation is not None:
            normalized.append(invocation)
    return normalized


def _normalize_pcl_segment(tokens: list[str]) -> tuple[str, bool] | None:
    index = 0
    while index < len(tokens) and (
        tokens[index] in {"env", "command"} or _ASSIGNMENT_RE.match(tokens[index])
    ):
        index += 1
    if index >= len(tokens):
        return None
    executable = Path(tokens[index]).name
    if executable == "pcl":
        index += 1
    elif _PYTHON_RE.match(executable) and tokens[index + 1 : index + 3] == ["-m", "pcl"]:
        index += 3
    else:
        return None
    help_probe = "--help" in tokens[index:]
    while index < len(tokens):
        token = tokens[index]
        if token == "--root":
            index += 2
            continue
        if token.startswith("--root=") or token == "--json":
            index += 1
            continue
        if token == "--version":
            return ("version", help_probe)
        if token == "--help":
            return ("help", True)
        if token.startswith("-"):
            index += 1
            continue
        command = token
        index += 1
        break
    else:
        return ("help", help_probe) if help_probe else None
    if command not in _KNOWN_SUBCOMMANDS and command not in _DIRECT_COMMANDS:
        return None
    if command in _KNOWN_SUBCOMMANDS:
        while index < len(tokens) and tokens[index].startswith("-"):
            index += 1
        if index < len(tokens) and tokens[index] in _KNOWN_SUBCOMMANDS[command]:
            command = f"{command} {tokens[index]}"
    return command, help_probe


def _classify_output(
    session: _SessionObservation,
    value: Any,
    *,
    call_id: str,
    is_error: bool | None = None,
) -> None:
    text = _output_text(value)
    result_status = _tool_result_status(value, is_error=is_error)
    commands = session.pcl_call_commands.get(call_id, Counter())
    if (
        commands
        and set(commands) == {"report skill-usage"}
        and result_status != "failure"
    ):
        return
    if not text and result_status != "failure":
        return
    observed = Counter[str]()
    if result_status == "success":
        if _has_typed_completed_with_risk(value):
            observed["completed_with_risk"] += 1
    else:
        for code, pattern in _FRICTION_PATTERNS.items():
            if pattern.search(text):
                observed[code] += 1
        if result_status == "failure" or _COMMAND_ERROR_RE.search(text):
            observed["command_error"] += 1
    if not observed:
        return

    session.friction.update(observed)
    for code, count in observed.items():
        for command in commands:
            _add_friction_command(
                session,
                code=code,
                command=command,
                count=count,
            )
    if observed.keys() & _RETRY_TRIGGER_CODES:
        session.pending_retry_commands = Counter({command: 1 for command in commands})


def _tool_result_status(value: Any, *, is_error: bool | None) -> str:
    if is_error is not None:
        return "failure" if is_error else "success"
    if isinstance(value, dict):
        ok = value.get("ok")
        if isinstance(ok, bool):
            return "success" if ok else "failure"
        for key in ("exit_code", "exitCode", "returncode", "return_code"):
            exit_code = value.get(key)
            if isinstance(exit_code, int) and not isinstance(exit_code, bool):
                return "success" if exit_code == 0 else "failure"
    for text in _result_text_leaves(value):
        header = text.lstrip()[:256]
        if re.match(r"Script failed with code [1-9]\d*", header, re.IGNORECASE):
            return "failure"
        process_status = re.search(
            r"(?:^|\n)Process exited with code (\d+)(?:\r?\n|$)",
            header,
            re.IGNORECASE,
        )
        if process_status:
            return "success" if int(process_status.group(1)) == 0 else "failure"
        stripped = text.strip()
        if stripped and stripped[0] == "{":
            try:
                payload = json.loads(stripped)
            except JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("ok"), bool):
                return "success" if payload["ok"] else "failure"
    return "unknown"


def _has_typed_completed_with_risk(value: Any) -> bool:
    for text in _result_text_leaves(value):
        stripped = text.strip()
        if stripped == "COMPLETED_WITH_RISK":
            return True
        if not stripped or stripped[0] not in "[{":
            continue
        try:
            payload = json.loads(stripped)
        except JSONDecodeError:
            continue
        if _has_completion_outcome(payload, expected="COMPLETED_WITH_RISK"):
            return True
    if isinstance(value, (dict, list)):
        return _has_completion_outcome(value, expected="COMPLETED_WITH_RISK")
    return False


def _has_completion_outcome(value: Any, *, expected: str) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"outcome", "completion_outcome"}:
                if isinstance(item, str) and item.upper() == expected:
                    return True
            if isinstance(item, (dict, list)) and _has_completion_outcome(
                item, expected=expected
            ):
                return True
    elif isinstance(value, list):
        return any(
            _has_completion_outcome(item, expected=expected)
            for item in value
            if isinstance(item, (dict, list))
        )
    return False


def _result_text_leaves(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _result_text_leaves(item)
    elif isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            yield text
        content = value.get("content")
        if content is not text:
            yield from _result_text_leaves(content)
        output = value.get("output")
        if output is not content and output is not text:
            yield from _result_text_leaves(output)


def _add_friction_command(
    session: _SessionObservation,
    *,
    code: str,
    command: str,
    count: int,
) -> None:
    session.friction_commands.setdefault(code, Counter())[command] += count


def _output_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_output_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_output_text(item) for item in value.values())
    return ""


def _merge_session(
    sessions: dict[str, _SessionObservation],
    incoming: _SessionObservation,
) -> None:
    current = sessions.get(incoming.key)
    if current is None:
        sessions[incoming.key] = incoming
        return
    current.workspace = current.workspace or incoming.workspace
    current.skill_seen_any = current.skill_seen_any or incoming.skill_seen_any
    current.skill_seen_in_window = current.skill_seen_in_window or incoming.skill_seen_in_window
    current.commands.update(incoming.commands)
    current.help_probes += incoming.help_probes
    current.help_probe_commands.update(incoming.help_probe_commands)
    current.friction.update(incoming.friction)
    for code, command_counts in incoming.friction_commands.items():
        current.friction_commands.setdefault(code, Counter()).update(command_counts)
    current.pcl_call_ids.update(incoming.pcl_call_ids)
    for call_id, command_counts in incoming.pcl_call_commands.items():
        current.pcl_call_commands.setdefault(call_id, Counter()).update(command_counts)


def _source_payload(scan: _SourceScan) -> dict[str, Any]:
    if scan.source == "cockpit":
        return {
            "status": "available" if scan.available else "unavailable",
            "files_scanned": scan.files_scanned,
            "parse_errors": scan.parse_errors,
            "control_plane_tasks": len(scan.cockpit_tasks),
        }
    included = [session for session in scan.sessions.values() if session.included]
    return {
        "status": "available" if scan.available else "unavailable",
        "files_scanned": scan.files_scanned,
        "parse_errors": scan.parse_errors,
        "skill_sessions": len(included),
        "sessions_with_pcl_commands": sum(1 for session in included if session.commands),
        "commands_detected": sum(sum(session.commands.values()) for session in included),
        "distinct_workspaces": len(
            {session.workspace for session in included if session.workspace}
        ),
    }


def _improvement_candidates(
    *,
    friction: Counter[str],
    friction_sessions: dict[str, int],
    friction_commands: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    definitions = {
        "finish_checks_not_configured": (
            "finish_check_bootstrap",
            "P0",
            "Keep finish-check setup actionable before terminal execution and regression-test it.",
        ),
        "guarded_execution_blocked": (
            "review_guarded_safe_command_coverage",
            "P0",
            "Reproduce blocked commands and add only exact safe argv contracts when justified.",
        ),
        "timeout": (
            "review_long_running_check_timeout",
            "P1",
            "Reproduce long checks and evaluate project-scoped timeout guidance or configuration.",
        ),
        "completed_with_risk": (
            "separate_expected_local_risk",
            "P1",
            "Review recurring risk classes and separate expected local state from product risk.",
        ),
        "help_probe": (
            "improve_command_discoverability",
            "P1",
            "Turn repeated help lookups into clearer next-action or command guidance.",
        ),
        "repeated_command": (
            "reduce_repeated_command_roundtrips",
            "P1",
            "Reproduce repeated command families and remove avoidable lifecycle roundtrips.",
        ),
        "command_error": (
            "triage_command_error_clusters",
            "P2",
            "Classify command errors with fixtures before treating them as product defects.",
        ),
    }
    candidates: list[dict[str, Any]] = []
    for friction_code, (code, priority, recommendation) in definitions.items():
        if not friction[friction_code]:
            continue
        evidence: dict[str, Any] = {
            "friction_code": friction_code,
            "session_count": friction_sessions[friction_code],
        }
        command_breakdown = friction_commands.get(friction_code, [])
        if command_breakdown:
            evidence["leading_command"] = command_breakdown[0]
        candidates.append(
            {
                "code": code,
                "priority": priority,
                "recommendation": recommendation,
                "evidence": evidence,
                "advisory": True,
            }
        )
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(candidates, key=lambda item: (priority_order[item["priority"]], item["code"]))
