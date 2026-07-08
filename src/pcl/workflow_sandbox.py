from __future__ import annotations

import json
import shutil
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .db import connect
from .events import append_event
from .errors import DataStoreError, InvalidInputError, ProjectNotInitializedError
from .ids import next_prefixed_id
from .paths import ProjectPaths
from .timeutil import utc_now_iso
from .workflow_proposal_validation import PROPOSAL_ID_RE, validate_workflow_proposal_text
from .workflow_verifier import verify_workflow_text


CONTRACT_VERSION = "workflow-sandbox/v1"
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
) -> dict[str, Any]:
    target = _load_file_target(paths, source_path)
    return _sandbox_loaded_target(paths, target, execute=execute, timeout_seconds=timeout_seconds)


def sandbox_workflow_proposal(
    paths: ProjectPaths,
    *,
    proposal_id: str,
    execute: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    target = _load_proposal_target(paths, proposal_id)
    return _sandbox_loaded_target(paths, target, execute=execute, timeout_seconds=timeout_seconds)


def sandbox_workflow_template(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    execute: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    target = _load_template_target(paths, workflow_id)
    return _sandbox_loaded_target(paths, target, execute=execute, timeout_seconds=timeout_seconds)


def plan_workflow_template_sandbox(
    paths: ProjectPaths,
    *,
    workflow_id: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    target = _load_template_target(paths, workflow_id)
    return _sandbox_loaded_target(paths, target, execute=False, timeout_seconds=timeout_seconds)["sandbox"]


def execute_planned_sandbox_command(
    paths: ProjectPaths,
    command: dict[str, Any],
    *,
    run_dir: Path,
    timeout_seconds: int,
) -> None:
    if not command.get("safe_to_run"):
        raise InvalidInputError(
            "Cannot execute a sandbox command that is not safe to run.",
            details={
                "raw_command": command.get("raw_command"),
                "blocked_reason": command.get("blocked_reason"),
            },
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    _execute_command(paths, command, run_dir=run_dir, timeout_seconds=timeout_seconds)


def _sandbox_loaded_target(
    paths: ProjectPaths,
    target: dict[str, str],
    *,
    execute: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if execute and target["target_type"] not in EXECUTABLE_TARGET_TYPES:
        raise InvalidInputError(
            "Workflow sandbox execution is only allowed for approved workflow templates.",
            details={"target_type": target["target_type"], "target_id": target["target_id"]},
        )
    timeout_seconds = _normalize_timeout(timeout_seconds)
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
    sandbox = _build_sandbox_result(
        target=target,
        verification=verification,
        commands=commands,
        execute=execute,
        timeout_seconds=timeout_seconds,
    )
    if execute:
        _execute_sandbox(paths, sandbox, timeout_seconds=timeout_seconds)
    _recount(sandbox)
    return {"ok": _sandbox_ok(sandbox), "sandbox": sandbox}


def _load_file_target(paths: ProjectPaths, source_path: str) -> dict[str, str]:
    _require_initialized(paths)
    path = Path(source_path)
    source = path if path.is_absolute() else paths.root / path
    if not source.exists() or not source.is_file():
        raise InvalidInputError(
            f"Workflow sandbox source does not exist: {source_path}",
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
        command["blocked_reason"] = f"project command key is not sandbox-allowlisted: {key}"
        return
    resolved = str(command["resolved_command"] or "")
    if not resolved:
        command["blocked_reason"] = f"project command is not configured: {key}"
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
    if executable not in SAFE_PROJECT_EXECUTABLES:
        command["blocked_reason"] = f"project command executable is not allowlisted: {executable}"
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
        command["blocked_reason"] = f"pcl command flag is controlled by the sandbox: {forbidden_flag}"
        return
    if len(argv) < 2:
        command["blocked_reason"] = "pcl command is missing a subcommand"
        return
    signature = tuple(argv[1:3]) if len(argv) >= 3 and argv[1] == "workflow" else (argv[1],)
    if signature not in SAFE_PCL_COMMANDS:
        command["blocked_reason"] = f"pcl command is not sandbox-allowlisted: {' '.join(signature)}"
        return
    _mark_safe(command)


def _mark_safe(command: dict[str, Any]) -> None:
    command["safe_to_run"] = True
    command["requires_human"] = False
    command["blocked_reason"] = ""


def _split_command(command: str) -> tuple[list[str], str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [], f"command cannot be parsed: {exc}"
    if not argv:
        return [], "command is empty"
    return argv, ""


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


def _build_sandbox_result(
    *,
    target: dict[str, str],
    verification: dict[str, Any],
    commands: list[dict[str, Any]],
    execute: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    sandbox = {
        "contract_version": CONTRACT_VERSION,
        "execute": execute,
        "timeout_seconds": timeout_seconds,
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
        "commands": commands,
    }
    _recount(sandbox)
    return sandbox


def _execute_sandbox(paths: ProjectPaths, sandbox: dict[str, Any], *, timeout_seconds: int) -> None:
    if not sandbox["verification"]["ok"]:
        return
    runnable = [command for command in sandbox["commands"] if command["safe_to_run"]]
    if not runnable:
        for command in sandbox["commands"]:
            if not command["safe_to_run"]:
                command["status"] = "skipped"
        return
    run_dir = _stage_sandbox_run_dir(paths)
    try:
        for command in sandbox["commands"]:
            if not command["safe_to_run"]:
                command["status"] = "skipped"
                continue
            _execute_command(paths, command, run_dir=run_dir, timeout_seconds=timeout_seconds)
        _recount(sandbox)
        _record_sandbox_evidence(paths, sandbox, stage_dir=run_dir)
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def _execute_command(
    paths: ProjectPaths,
    command: dict[str, Any],
    *,
    run_dir: Path,
    timeout_seconds: int,
) -> None:
    argv = _execution_argv(paths, command)
    stdout_path = run_dir / f"{command['index']:02d}-{_safe_file_token(command['step_id'])}.stdout.txt"
    stderr_path = run_dir / f"{command['index']:02d}-{_safe_file_token(command['step_id'])}.stderr.txt"
    try:
        completed = subprocess.run(
            argv,
            cwd=paths.root,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=timeout_seconds,
        )
        command["exit_code"] = completed.returncode
        command["status"] = "passed" if completed.returncode == 0 else "failed"
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        command["exit_code"] = None
        command["status"] = "failed"
        command["timed_out"] = True
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr) or f"Timed out after {timeout_seconds} seconds.\n"
    except (OSError, subprocess.SubprocessError) as exc:
        command["exit_code"] = None
        command["status"] = "failed"
        stdout = ""
        stderr = f"{exc.__class__.__name__}: {exc}\n"
    stdout_path.write_text(stdout or "", encoding="utf-8")
    stderr_path.write_text(stderr or "", encoding="utf-8")
    command["stdout_path"] = str(stdout_path.relative_to(paths.root))
    command["stderr_path"] = str(stderr_path.relative_to(paths.root))


def _execution_argv(paths: ProjectPaths, command: dict[str, Any]) -> list[str]:
    argv = [str(part) for part in command["argv"]]
    if command["kind"] == "pcl":
        return [sys.executable, "-m", "pcl", "--root", str(paths.root), *argv[1:]]
    return argv


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _stage_sandbox_run_dir(paths: ProjectPaths) -> Path:
    tmp_parent = paths.loop_dir / "tmp"
    try:
        tmp_parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="workflow-sandbox-", dir=tmp_parent))
    except OSError as exc:
        raise DataStoreError(f"Could not stage workflow sandbox evidence: {exc}") from exc


def _record_sandbox_evidence(paths: ProjectPaths, sandbox: dict[str, Any], *, stage_dir: Path) -> None:
    conn = connect(paths.db_path)
    final_dir: Path | None = None
    try:
        evidence_id = next_prefixed_id(conn, "evidence", "E")
        final_dir = paths.evidence_dir / "workflow-sandbox" / evidence_id
        if final_dir.exists():
            raise DataStoreError(f"Could not store workflow sandbox evidence: destination exists at {final_dir}")
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        stage_dir.replace(final_dir)
        _rebase_sandbox_paths(paths, sandbox, final_dir=final_dir)
        result_path = final_dir / "result.json"
        sandbox["evidence_id"] = evidence_id
        sandbox["evidence_path"] = str(result_path.relative_to(paths.root))
        result_path.write_text(
            json.dumps(sandbox, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        created_at = utc_now_iso()
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sandbox["evidence_id"],
                "workflow_sandbox_run",
                sandbox["evidence_path"],
                f"pcl workflow sandbox --template {sandbox['target_id']} --execute",
                _sandbox_summary(sandbox),
                created_at,
            ),
        )
        append_event(
            conn=conn,
            events_path=paths.events_path,
            event_type="workflow_sandbox_executed",
            entity_type="workflow",
            entity_id=sandbox["target_id"],
            payload={
                "contract_version": CONTRACT_VERSION,
                "target_type": sandbox["target_type"],
                "target_id": sandbox["target_id"],
                "workflow_id": sandbox["workflow_id"],
                "evidence_id": sandbox["evidence_id"],
                "evidence_path": sandbox["evidence_path"],
                "command_count": sandbox["command_count"],
                "executed_count": sandbox["executed_count"],
                "skipped_count": sandbox["skipped_count"],
                "failed_count": sandbox["failed_count"],
                "ok": _sandbox_ok(sandbox),
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


def _sandbox_summary(sandbox: dict[str, Any]) -> str:
    status = "passed" if _sandbox_ok(sandbox) else "failed"
    return (
        f"Workflow sandbox {status}: target={sandbox['target_id']} "
        f"executed={sandbox['executed_count']} skipped={sandbox['skipped_count']} "
        f"failed={sandbox['failed_count']}"
    )


def _recount(sandbox: dict[str, Any]) -> None:
    commands = sandbox["commands"]
    sandbox["command_count"] = len(commands)
    sandbox["safe_command_count"] = len([command for command in commands if command["safe_to_run"]])
    sandbox["blocked_command_count"] = len([command for command in commands if not command["safe_to_run"]])
    sandbox["executed_count"] = len([command for command in commands if command["status"] in {"passed", "failed"}])
    sandbox["skipped_count"] = len([command for command in commands if command["status"] == "skipped"])
    sandbox["failed_count"] = len([command for command in commands if command["status"] == "failed"])
    sandbox["safe_to_execute"] = bool(sandbox["verification"]["ok"] and sandbox["safe_command_count"] > 0)


def _sandbox_ok(sandbox: dict[str, Any]) -> bool:
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
            "Workflow sandbox timeout must be at least 1 second.",
            details={"timeout_seconds": timeout_seconds},
        )
    if timeout_seconds > 600:
        raise InvalidInputError(
            "Workflow sandbox timeout must be 600 seconds or less.",
            details={"timeout_seconds": timeout_seconds},
        )
    return timeout_seconds


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
