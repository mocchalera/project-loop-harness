from __future__ import annotations

import json
import shutil
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .db import connect_mutation
from .events import append_event
from .errors import DataStoreError, InvalidInputError, ProjectNotInitializedError
from .guarded_process import DEFAULT_MAX_OUTPUT_BYTES, execute_guarded_process
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .redaction import compile_redaction_patterns
from .timeutil import utc_now_iso
from .workflow_proposal_validation import PROPOSAL_ID_RE, validate_workflow_proposal_text
from .workflow_verifier import verify_workflow_text


CONTRACT_VERSION = "guarded-executor/v1"
LEGACY_CONTRACT_VERSION = "workflow-sandbox/v1"
LEGACY_DEPRECATION = (
    "`pcl workflow sandbox` is deprecated and will be removed after the 0.3.x release line; "
    "use `pcl workflow guard` instead. This guarded executor does not provide OS isolation."
)
PROJECT_COMMAND_PREFIX = "project.commands."
EXECUTABLE_TARGET_TYPES = {"workflow_template"}
SAFE_PCL_COMMANDS = {
    ("doctor",),
    ("next",),
    ("render",),
    ("validate",),
    ("workflow", "verify"),
}
SAFE_PROJECT_COMMAND_KEYS = {"lint", "typecheck", "test", "e2e", "build"}
FINISH_CHECK_COMMAND_KEYS = ("lint", "typecheck", "test", "e2e", "build")
BLOCKED_PROJECT_EXECUTABLES = {
    "bash",
    "chmod",
    "chown",
    "curl",
    "docker",
    "fish",
    "gh",
    "git",
    "kubectl",
    "osascript",
    "pip",
    "rm",
    "scp",
    "sh",
    "ssh",
    "sudo",
    "terraform",
    "wget",
    "zsh",
}
SAFE_PROJECT_EXECUTABLES = {
    "bun",
    "cargo",
    "go",
    "mypy",
    "npm",
    "pnpm",
    "pytest",
    "pyright",
    "ruff",
    "yarn",
}
SAFE_PYTHON_MODULES = {"mypy", "pytest", "pyright", "ruff"}
SAFE_NODE_MODES = {"--check", "--test"}
FAIL_OPEN_CHECK_COMMAND_REASON = "fail_open_check_command"
FAIL_OPEN_FALLBACK_EXECUTABLES = {"true", "echo", "printf"}
FORBIDDEN_PCL_FLAGS = {"--root"}
FORBIDDEN_PROJECT_TOKENS = {"deploy", "install", "publish", "release", "upload"}
FORBIDDEN_COMMAND_FRAGMENTS = (
    ".project-loop/events.jsonl",
    ".project-loop/project.db",
    ".env",
    "$(",
    "&&",
    "||",
    ";",
    "<",
    ">",
    "`",
    "curl ",
    "rm -rf",
    "scp ",
    "secrets/",
    "ssh ",
    "sudo ",
    "wget ",
    "|",
)


def sandbox_workflow_file(
    paths: ProjectPaths,
    *,
    source_path: str,
    execute: bool = False,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    target = _load_file_target(paths, source_path)
    return _guard_loaded_target(
        paths,
        target,
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        legacy_alias=True,
        allowed_env_names=allowed_env_names,
    )


def sandbox_workflow_proposal(
    paths: ProjectPaths,
    *,
    proposal_id: str,
    execute: bool = False,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    target = _load_proposal_target(paths, proposal_id)
    return _guard_loaded_target(
        paths,
        target,
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        legacy_alias=True,
        allowed_env_names=allowed_env_names,
    )


def sandbox_workflow_template(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    execute: bool = False,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    target = _load_template_target(paths, workflow_id)
    return _guard_loaded_target(
        paths,
        target,
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        legacy_alias=True,
        allowed_env_names=allowed_env_names,
    )


def guard_workflow_file(
    paths: ProjectPaths,
    *,
    source_path: str,
    execute: bool = False,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    redaction_patterns: Iterable[str] = (),
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    return _guard_loaded_target(
        paths,
        _load_file_target(paths, source_path),
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        redaction_patterns=redaction_patterns,
        allowed_env_names=allowed_env_names,
    )


def guard_workflow_proposal(
    paths: ProjectPaths,
    *,
    proposal_id: str,
    execute: bool = False,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    redaction_patterns: Iterable[str] = (),
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    return _guard_loaded_target(
        paths,
        _load_proposal_target(paths, proposal_id),
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        redaction_patterns=redaction_patterns,
        allowed_env_names=allowed_env_names,
    )


def guard_workflow_template(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    execute: bool = False,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    redaction_patterns: Iterable[str] = (),
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    return _guard_loaded_target(
        paths,
        _load_template_target(paths, workflow_id),
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        redaction_patterns=redaction_patterns,
        allowed_env_names=allowed_env_names,
    )


def plan_workflow_template_sandbox(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Compatibility API for callers migrating to plan_workflow_template_guard()."""
    return plan_workflow_template_guard(
        paths,
        workflow_id=workflow_id,
        timeout_seconds=timeout_seconds,
    )


def plan_workflow_template_guard(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    timeout_seconds: int = 120,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    target = _load_template_target(paths, workflow_id)
    return _guard_loaded_target(
        paths,
        target,
        execute=False,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )["guarded_executor"]


def execute_planned_sandbox_command(
    paths: ProjectPaths,
    command: dict[str, Any],
    *,
    run_dir: Path,
    timeout_seconds: int,
) -> None:
    """Compatibility API for callers migrating to execute_planned_guarded_command()."""
    execute_planned_guarded_command(
        paths,
        command,
        run_dir=run_dir,
        timeout_seconds=timeout_seconds,
    )


def execute_planned_guarded_command(
    paths: ProjectPaths,
    command: dict[str, Any],
    *,
    run_dir: Path,
    timeout_seconds: int,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    redaction_patterns: Iterable[str] = (),
    allowed_env_names: Iterable[str] = (),
) -> None:
    if not command.get("safe_to_run"):
        raise InvalidInputError(
            "Cannot execute a guarded command that is not safe to run.",
            details={
                "raw_command": command.get("raw_command"),
                "blocked_reason": command.get("blocked_reason"),
            },
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    _execute_command(
        paths,
        command,
        run_dir=run_dir,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        redaction_patterns=redaction_patterns,
        allowed_env_names=allowed_env_names,
    )


def plan_guarded_project_checks(paths: ProjectPaths) -> list[dict[str, Any]]:
    """Plan configured finish checks with the guarded executor allowlist."""

    project_commands = _load_project_commands(paths)
    planned: list[dict[str, Any]] = []
    for key in FINISH_CHECK_COMMAND_KEYS:
        if not project_commands.get(key):
            continue
        planned.append(
            _plan_command(
                "finish_checks",
                len(planned) + 1,
                len(planned) + 1,
                f"{PROJECT_COMMAND_PREFIX}{key}",
                project_commands,
            )
        )
    return planned


def _guard_loaded_target(
    paths: ProjectPaths,
    target: dict[str, str],
    *,
    execute: bool,
    timeout_seconds: int,
    max_output_bytes: int,
    redaction_patterns: Iterable[str] = (),
    legacy_alias: bool = False,
    allowed_env_names: Iterable[str] = (),
) -> dict[str, Any]:
    if execute and target["target_type"] not in EXECUTABLE_TARGET_TYPES:
        raise InvalidInputError(
            "Guarded workflow execution is only allowed for approved workflow templates.",
            details={"target_type": target["target_type"], "target_id": target["target_id"]},
        )
    timeout_seconds = _normalize_timeout(timeout_seconds)
    max_output_bytes = _normalize_max_output_bytes(max_output_bytes)
    verification = verify_workflow_text(
        target["text"],
        source_label=target["source_label"],
        path=target["path"],
        target_type=target["target_type"],
        target_id=target["target_id"],
        expected_workflow_id=target.get("expected_workflow_id") or None,
    )
    data = _parse_verified_workflow(target["text"], target["source_label"])
    project_commands = _load_project_commands(paths)
    commands = _extract_command_plans(data, project_commands)
    if legacy_alias:
        _apply_legacy_command_language(commands)
    guarded_executor = _build_guarded_executor_result(
        target=target,
        verification=verification,
        commands=commands,
        execute=execute,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        legacy_alias=legacy_alias,
    )
    if execute:
        _execute_guarded(
            paths,
            guarded_executor,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            redaction_patterns=redaction_patterns,
            allowed_env_names=allowed_env_names,
        )
    _recount(guarded_executor)
    key = "sandbox" if legacy_alias else "guarded_executor"
    result = {"ok": _guarded_ok(guarded_executor), key: guarded_executor}
    if legacy_alias:
        result["deprecation"] = LEGACY_DEPRECATION
    return result


def _load_file_target(paths: ProjectPaths, source_path: str) -> dict[str, str]:
    _require_initialized(paths)
    path = Path(source_path)
    source = path if path.is_absolute() else paths.root / path
    if not source.exists() or not source.is_file():
        raise InvalidInputError(
            f"Workflow guard source does not exist: {source_path}",
            details={"source_path": source_path},
        )
    return {
        "target_type": "file",
        "target_id": _display_path(paths, source),
        "source_label": _display_path(paths, source),
        "path": _display_path(paths, source),
        "text": source.read_text(encoding="utf-8"),
    }


def _load_proposal_target(paths: ProjectPaths, proposal_id: str) -> dict[str, str]:
    _require_initialized(paths)
    if not PROPOSAL_ID_RE.match(proposal_id):
        raise InvalidInputError(
            f"Invalid workflow proposal id: {proposal_id}",
            details={"proposal_id": proposal_id},
        )
    path = paths.workflow_proposals_dir / f"{proposal_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow proposal does not exist: {proposal_id}",
            details={"proposal_id": proposal_id, "path": str(path)},
        )
    return {
        "target_type": "workflow_proposal",
        "target_id": proposal_id,
        "source_label": str(path.relative_to(paths.root)),
        "path": str(path.relative_to(paths.root)),
        "text": path.read_text(encoding="utf-8"),
    }


def _load_template_target(paths: ProjectPaths, workflow_id: str) -> dict[str, str]:
    _require_initialized(paths)
    if not _is_identifier(workflow_id):
        raise InvalidInputError(
            f"Invalid workflow id: {workflow_id}",
            details={"workflow_id": workflow_id},
        )
    path = paths.workflows_dir / f"{workflow_id}.yaml"
    if not path.exists():
        raise InvalidInputError(
            f"Workflow template does not exist: {workflow_id}",
            details={"workflow_id": workflow_id, "path": str(path)},
        )
    return {
        "target_type": "workflow_template",
        "target_id": workflow_id,
        "source_label": str(path.relative_to(paths.root)),
        "path": str(path.relative_to(paths.root)),
        "expected_workflow_id": workflow_id,
        "text": path.read_text(encoding="utf-8"),
    }


def _parse_verified_workflow(text: str, source_label: str) -> dict[str, Any]:
    try:
        return validate_workflow_proposal_text(text, source_label=source_label)
    except InvalidInputError:
        return {}


def _load_project_commands(paths: ProjectPaths) -> dict[str, str]:
    config_path = paths.root / "pcl.yaml"
    if not config_path.exists():
        return {}
    commands: dict[str, str] = {}
    in_commands = False
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("commands:"):
            in_commands = True
            continue
        if in_commands and raw_line and not raw_line.startswith(" "):
            break
        if not in_commands or not raw_line.startswith("  ") or ":" not in raw_line:
            continue
        key, value = raw_line.strip().split(":", 1)
        value = _strip_yaml_string(value.strip())
        if value:
            commands[key.strip()] = value
    return commands


def _strip_yaml_string(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _extract_command_plans(
    data: dict[str, Any],
    project_commands: dict[str, str],
) -> list[dict[str, Any]]:
    steps = data.get("steps")
    if not isinstance(steps, list):
        return []
    commands: list[dict[str, Any]] = []
    sequence = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or f"step_{len(commands) + 1}")
        raw_commands: list[str] = []
        if "command" in step:
            raw_commands.append(str(step["command"]))
        if "commands" in step and isinstance(step["commands"], list):
            raw_commands.extend(str(command) for command in step["commands"])
        for index, raw_command in enumerate(raw_commands, start=1):
            sequence += 1
            commands.append(_plan_command(step_id, index, sequence, raw_command, project_commands))
    return commands


def _plan_command(
    step_id: str,
    index: int,
    sequence: int,
    raw_command: str,
    project_commands: dict[str, str],
) -> dict[str, Any]:
    command = {
        "id": f"{step_id}:{index}",
        "index": sequence,
        "step_id": step_id,
        "raw_command": raw_command,
        "kind": "unsupported",
        "resolved_command": "",
        "argv": [],
        "safe_to_run": False,
        "requires_human": True,
        "blocked_reason": "",
        "status": "planned",
        "exit_code": None,
        "timed_out": False,
        "stdout_path": "",
        "stderr_path": "",
    }
    stripped = raw_command.strip()
    if not stripped:
        command["blocked_reason"] = "command is empty"
        return command
    if stripped.startswith(PROJECT_COMMAND_PREFIX):
        key = stripped.removeprefix(PROJECT_COMMAND_PREFIX)
        command["kind"] = "project_command"
        command["resolved_command"] = project_commands.get(key, "")
        _mark_project_command_safety(command, key=key)
        return command
    if stripped.startswith("pcl "):
        command["kind"] = "pcl"
        command["resolved_command"] = stripped
        _mark_pcl_command_safety(command)
        return command
    command["blocked_reason"] = "only pcl commands and project.commands references are supported"
    return command


def _mark_project_command_safety(command: dict[str, Any], *, key: str) -> None:
    if key not in SAFE_PROJECT_COMMAND_KEYS:
        command["blocked_reason"] = f"project command key is not guarded-executor-allowlisted: {key}"
        return
    resolved = str(command["resolved_command"] or "")
    if not resolved:
        command["blocked_reason"] = f"project command is not configured: {key}"
        return
    if _is_fail_open_check_command(resolved):
        command["blocked_reason"] = FAIL_OPEN_CHECK_COMMAND_REASON
        return
    unsafe = _forbidden_fragment(resolved)
    if unsafe:
        command["blocked_reason"] = f"command contains forbidden fragment: {unsafe}"
        return
    argv, error = _split_command(resolved)
    if error:
        command["blocked_reason"] = error
        return
    command["argv"] = argv
    executable = Path(argv[0]).name
    if executable in BLOCKED_PROJECT_EXECUTABLES:
        command["blocked_reason"] = f"project command executable is blocked: {executable}"
        return
    forbidden_token = _forbidden_project_token(argv)
    if forbidden_token:
        command["blocked_reason"] = f"project command token requires human approval: {forbidden_token}"
        return
    if executable in {"python", "python3"}:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in SAFE_PYTHON_MODULES:
            _mark_safe(command)
            return
        command["blocked_reason"] = "python project commands must use -m with an allowlisted test or lint module"
        return
    if executable == "node":
        _mark_node_command_safety(command, argv)
        return
    if executable not in SAFE_PROJECT_EXECUTABLES:
        command["blocked_reason"] = f"project command executable is not allowlisted: {executable}"
        return
    _mark_safe(command)


def _mark_node_command_safety(command: dict[str, Any], argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in SAFE_NODE_MODES:
        command["blocked_reason"] = "node project commands must use --test or --check"
        return
    mode = argv[1]
    operands = argv[2:]
    if mode == "--check" and len(operands) != 1:
        command["blocked_reason"] = "node --check requires exactly one project-relative JavaScript file"
        return
    for operand in operands:
        path = Path(operand)
        if operand.startswith("-") or path.is_absolute() or ".." in path.parts:
            command["blocked_reason"] = "node verification operands must be project-relative paths"
            return
        if mode == "--check" and path.suffix not in {".js", ".mjs", ".cjs"}:
            command["blocked_reason"] = "node --check requires a JavaScript file"
            return
    _mark_safe(command)


def _mark_pcl_command_safety(command: dict[str, Any]) -> None:
    resolved = str(command["resolved_command"] or "")
    unsafe = _forbidden_fragment(resolved)
    if unsafe:
        command["blocked_reason"] = f"command contains forbidden fragment: {unsafe}"
        return
    argv, error = _split_command(resolved)
    if error:
        command["blocked_reason"] = error
        return
    command["argv"] = argv
    if not argv or argv[0] != "pcl":
        command["blocked_reason"] = "pcl command must start with `pcl`"
        return
    forbidden_flag = _forbidden_pcl_flag(argv)
    if forbidden_flag:
        command["blocked_reason"] = f"pcl command flag is controlled by the guarded executor: {forbidden_flag}"
        return
    if len(argv) < 2:
        command["blocked_reason"] = "pcl command is missing a subcommand"
        return
    signature = tuple(argv[1:3]) if len(argv) >= 3 and argv[1] == "workflow" else (argv[1],)
    if signature not in SAFE_PCL_COMMANDS:
        command["blocked_reason"] = f"pcl command is not guarded-executor-allowlisted: {' '.join(signature)}"
        return
    _mark_safe(command)


def _mark_safe(command: dict[str, Any]) -> None:
    command["safe_to_run"] = True
    command["requires_human"] = False
    command["blocked_reason"] = ""


def _apply_legacy_command_language(commands: list[dict[str, Any]]) -> None:
    for command in commands:
        reason = str(command.get("blocked_reason") or "")
        command["blocked_reason"] = reason.replace(
            "guarded-executor-allowlisted",
            "sandbox-allowlisted",
        ).replace(
            "controlled by the guarded executor",
            "controlled by the sandbox",
        )


def _split_command(command: str) -> tuple[list[str], str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [], f"command cannot be parsed: {exc}"
    if not argv:
        return [], "command is empty"
    return argv, ""


def _is_fail_open_check_command(command: str) -> bool:
    """Recognize bounded shell fallbacks that turn a failed check into success.

    This deliberately is not a general shell parser. It tokenizes quoting so a
    literal ``|| true`` argument is not mistaken for a shell operator, then
    recognizes only direct success fallbacks after ``||``: true, echo, printf,
    the ``:`` no-op, and ``exit 0``.
    """

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False

    for index, token in enumerate(tokens[:-1]):
        if token != "||":
            continue
        fallback = Path(tokens[index + 1]).name.lower()
        if fallback in FAIL_OPEN_FALLBACK_EXECUTABLES or fallback == ":":
            return True
        if fallback == "exit" and index + 2 < len(tokens) and tokens[index + 2] == "0":
            return True
    return False


def _forbidden_pcl_flag(argv: list[str]) -> str:
    for token in argv[1:]:
        if token in FORBIDDEN_PCL_FLAGS:
            return token
        if token.startswith("--root="):
            return "--root"
    return ""


def _forbidden_project_token(argv: list[str]) -> str:
    for token in argv[1:]:
        normalized = token.strip().lower()
        if normalized in FORBIDDEN_PROJECT_TOKENS:
            return normalized
    return ""


def _forbidden_fragment(command: str) -> str:
    lowered = command.lower()
    for fragment in FORBIDDEN_COMMAND_FRAGMENTS:
        if fragment in lowered:
            return fragment
    return ""


def _build_guarded_executor_result(
    *,
    target: dict[str, str],
    verification: dict[str, Any],
    commands: list[dict[str, Any]],
    execute: bool,
    timeout_seconds: int,
    max_output_bytes: int,
    legacy_alias: bool,
) -> dict[str, Any]:
    guarded_executor = {
        "contract_version": LEGACY_CONTRACT_VERSION if legacy_alias else CONTRACT_VERSION,
        "surface": "guarded_executor",
        "legacy_alias": legacy_alias,
        "execute": execute,
        "timeout_seconds": timeout_seconds,
        "max_output_bytes": max_output_bytes,
        "target_type": target["target_type"],
        "target_id": target["target_id"],
        "workflow_id": verification.get("workflow_id") or "",
        "path": target["path"],
        "verification": verification,
        "safe_to_execute": False,
        "command_count": 0,
        "safe_command_count": 0,
        "blocked_command_count": 0,
        "executed_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "evidence_id": "",
        "evidence_path": "",
        "output_truncated": False,
        "redacted": False,
        "permission_contract": {
            "backend": "host_subprocess",
            "command_format": "argv_list",
            "shell": False,
            "working_directory": "project_root",
            "environment_inheritance": "allowlist",
            "os_isolation": False,
            "network_isolation": False,
            "filesystem_isolation": False,
        },
        "redaction_contract": {
            "enabled": True,
            "configurable_patterns": True,
            "secret_scanner": False,
            "raw_output_persisted": False,
        },
        "commands": commands,
    }
    _recount(guarded_executor)
    return guarded_executor


def _execute_guarded(
    paths: ProjectPaths,
    guarded_executor: dict[str, Any],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
    redaction_patterns: Iterable[str],
    allowed_env_names: Iterable[str],
) -> None:
    if not guarded_executor["verification"]["ok"]:
        return
    runnable = [command for command in guarded_executor["commands"] if command["safe_to_run"]]
    if not runnable:
        for command in guarded_executor["commands"]:
            if not command["safe_to_run"]:
                command["status"] = "skipped"
        return
    run_dir = _stage_sandbox_run_dir(paths)
    try:
        for command in guarded_executor["commands"]:
            if not command["safe_to_run"]:
                command["status"] = "skipped"
                continue
            _execute_command(
                paths,
                command,
                run_dir=run_dir,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
                redaction_patterns=redaction_patterns,
                allowed_env_names=allowed_env_names,
            )
        _recount(guarded_executor)
        _record_guarded_evidence(paths, guarded_executor, stage_dir=run_dir)
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def _execute_command(
    paths: ProjectPaths,
    command: dict[str, Any],
    *,
    run_dir: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    redaction_patterns: Iterable[str],
    allowed_env_names: Iterable[str] = (),
) -> None:
    argv = _execution_argv(paths, command)
    stdout_path = run_dir / f"{command['index']:02d}-{_safe_file_token(command['step_id'])}.stdout.txt"
    stderr_path = run_dir / f"{command['index']:02d}-{_safe_file_token(command['step_id'])}.stderr.txt"
    process_result = execute_guarded_process(
        argv,
        cwd=paths.root,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        redaction_patterns=compile_redaction_patterns(redaction_patterns),
        additional_allowed_env_names=allowed_env_names,
    )
    command["exit_code"] = process_result["exit_code"]
    command["status"] = "passed" if process_result["exit_code"] == 0 else "failed"
    command["timed_out"] = process_result["timed_out"]
    command["stdout_path"] = str(stdout_path.relative_to(paths.root))
    command["stderr_path"] = str(stderr_path.relative_to(paths.root))
    command["stdout"] = process_result["stdout"]
    command["stderr"] = process_result["stderr"]
    command["output_truncated"] = process_result["output_truncated"]
    command["redacted"] = process_result["redacted"]
    command["termination"] = process_result["termination"]
    command["failure_kind"] = process_result["failure_kind"]
    command["permission_contract"] = process_result["permission_contract"]


def _execution_argv(paths: ProjectPaths, command: dict[str, Any]) -> list[str]:
    argv = [str(part) for part in command["argv"]]
    if command["kind"] == "pcl":
        return [sys.executable, "-m", "pcl", "--root", str(paths.root), *argv[1:]]
    return argv


def _stage_sandbox_run_dir(paths: ProjectPaths) -> Path:
    tmp_parent = paths.loop_dir / "tmp"
    try:
        tmp_parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="guarded-executor-", dir=tmp_parent))
    except OSError as exc:
        raise DataStoreError(f"Could not stage guarded executor evidence: {exc}") from exc


def _record_guarded_evidence(
    paths: ProjectPaths,
    guarded_executor: dict[str, Any],
    *,
    stage_dir: Path,
) -> None:
    conn = connect_mutation(paths)
    final_dir: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        legacy_alias = bool(guarded_executor["legacy_alias"])
        evidence_dir_name = "workflow-sandbox" if legacy_alias else "guarded-executor"
        final_dir = paths.evidence_dir / evidence_dir_name / evidence_id
        if final_dir.exists():
            raise DataStoreError(f"Could not store guarded executor evidence: destination exists at {final_dir}")
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        stage_dir.replace(final_dir)
        _rebase_sandbox_paths(paths, guarded_executor, final_dir=final_dir)
        result_path = final_dir / "result.json"
        guarded_executor["evidence_id"] = evidence_id
        guarded_executor["evidence_path"] = str(result_path.relative_to(paths.root))
        result_path.write_text(
            json.dumps(guarded_executor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        created_at = utc_now_iso()
        evidence_type = "workflow_sandbox_run" if legacy_alias else "guarded_executor_run"
        command_name = "sandbox" if legacy_alias else "guard"
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guarded_executor["evidence_id"],
                evidence_type,
                guarded_executor["evidence_path"],
                f"pcl workflow {command_name} --template {guarded_executor['target_id']} --execute",
                _guarded_summary(guarded_executor),
                created_at,
            ),
        )
        event_type = "workflow_sandbox_executed" if legacy_alias else "guarded_executor_executed"
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type=event_type,
            entity_type="workflow",
            entity_id=guarded_executor["target_id"],
            payload={
                "contract_version": guarded_executor["contract_version"],
                "surface": "guarded_executor",
                "legacy_alias": legacy_alias,
                "target_type": guarded_executor["target_type"],
                "target_id": guarded_executor["target_id"],
                "workflow_id": guarded_executor["workflow_id"],
                "evidence_id": guarded_executor["evidence_id"],
                "evidence_path": guarded_executor["evidence_path"],
                "command_count": guarded_executor["command_count"],
                "executed_count": guarded_executor["executed_count"],
                "skipped_count": guarded_executor["skipped_count"],
                "failed_count": guarded_executor["failed_count"],
                "output_truncated": guarded_executor["output_truncated"],
                "redacted": guarded_executor["redacted"],
                "ok": _guarded_ok(guarded_executor),
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        if final_dir is not None and final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        raise
    finally:
        conn.close()


def _rebase_sandbox_paths(paths: ProjectPaths, sandbox: dict[str, Any], *, final_dir: Path) -> None:
    for command in sandbox["commands"]:
        for key in ("stdout_path", "stderr_path"):
            if not command.get(key):
                continue
            command[key] = str((final_dir / Path(str(command[key])).name).relative_to(paths.root))
        for stream_name in ("stdout", "stderr"):
            stream = command.get(stream_name)
            if not isinstance(stream, dict) or not stream.get("path"):
                continue
            stream["path"] = str(
                (final_dir / Path(str(stream["path"])).name).relative_to(paths.root)
            )


def _guarded_summary(guarded_executor: dict[str, Any]) -> str:
    status = "passed" if _guarded_ok(guarded_executor) else "failed"
    return (
        f"Guarded executor {status}: target={guarded_executor['target_id']} "
        f"executed={guarded_executor['executed_count']} skipped={guarded_executor['skipped_count']} "
        f"failed={guarded_executor['failed_count']} "
        f"truncated={guarded_executor['output_truncated']} redacted={guarded_executor['redacted']}"
    )


def _recount(sandbox: dict[str, Any]) -> None:
    commands = sandbox["commands"]
    sandbox["command_count"] = len(commands)
    sandbox["safe_command_count"] = len([command for command in commands if command["safe_to_run"]])
    sandbox["blocked_command_count"] = len([command for command in commands if not command["safe_to_run"]])
    sandbox["executed_count"] = len([command for command in commands if command["status"] in {"passed", "failed"}])
    sandbox["skipped_count"] = len([command for command in commands if command["status"] == "skipped"])
    sandbox["failed_count"] = len([command for command in commands if command["status"] == "failed"])
    sandbox["output_truncated"] = any(command.get("output_truncated", False) for command in commands)
    sandbox["redacted"] = any(command.get("redacted", False) for command in commands)
    sandbox["safe_to_execute"] = bool(sandbox["verification"]["ok"] and sandbox["safe_command_count"] > 0)


def _guarded_ok(sandbox: dict[str, Any]) -> bool:
    if not sandbox["verification"]["ok"]:
        return False
    if sandbox["execute"]:
        if sandbox["safe_command_count"] == 0:
            return False
        return sandbox["failed_count"] == 0
    return True


def _safe_file_token(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value) or "command"


def _normalize_timeout(timeout_seconds: int) -> int:
    if timeout_seconds < 1:
        raise InvalidInputError(
            "Guarded executor timeout must be at least 1 second.",
            details={"timeout_seconds": timeout_seconds},
        )
    if timeout_seconds > 600:
        raise InvalidInputError(
            "Guarded executor timeout must be 600 seconds or less.",
            details={"timeout_seconds": timeout_seconds},
        )
    return timeout_seconds


def _normalize_max_output_bytes(max_output_bytes: int) -> int:
    if max_output_bytes < 1:
        raise InvalidInputError(
            "Guarded executor output cap must be at least 1 byte.",
            details={"max_output_bytes": max_output_bytes},
        )
    if max_output_bytes > 67_108_864:
        raise InvalidInputError(
            "Guarded executor output cap must be 67108864 bytes or less.",
            details={"max_output_bytes": max_output_bytes},
        )
    return max_output_bytes


def _is_identifier(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"_", "-"} for char in value)


def _display_path(paths: ProjectPaths, path: Path) -> str:
    try:
        return str(path.relative_to(paths.root))
    except ValueError:
        return str(path)


def _require_initialized(paths: ProjectPaths) -> None:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))
