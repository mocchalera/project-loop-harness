from __future__ import annotations

from dataclasses import dataclass
import configparser
import json
from pathlib import Path
import re
import shlex
from typing import Any

from .db import initialize_database
from .db import connect_mutation
from .events import append_event
from .migrations import migration_status
from .paths import ProjectPaths
from .resources import copy_tree_resource, list_resource_files, read_text_resource


DEFAULT_DIRS = [
    "goals",
    "workflows",
    "workflow-proposals",
    "dashboard",
    "evidence/agent-runs",
    "evidence/test-results",
    "evidence/command-logs",
    "evidence/context-receipts",
    "evidence/adhoc",
    "exports",
    "reports",
    "worktrees",
    "tmp",
    "cache",
]

VERIFICATION_COMMAND_KEYS = ("lint", "typecheck", "test", "e2e", "build")
CONFIG_COMMAND_KEYS = ("install", *VERIFICATION_COMMAND_KEYS)
SAFE_NODE_SCRIPT_EXECUTABLES = {
    "ava",
    "biome",
    "cypress",
    "eslint",
    "jest",
    "mocha",
    "next",
    "playwright",
    "prettier",
    "tsc",
    "vite",
    "vitest",
}


@dataclass(frozen=True)
class InitResult:
    root: Path
    created: bool
    event_appended: bool
    repaired_config_commands: tuple[str, ...]


@dataclass(frozen=True)
class InitPlanEntry:
    action: str
    path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "path": self.path,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class InitPlan:
    root: Path
    changes: list[InitPlanEntry]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "root": str(self.root),
            "dry_run": True,
            "changes": [entry.to_dict() for entry in self.changes],
            "errors": self.errors,
        }


def append_block_once(path: Path, marker: str, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in existing:
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "\n" + block.strip() + "\n", encoding="utf-8")


def plan_init_project(
    paths: ProjectPaths,
    *,
    overwrite: bool = False,
    with_claude: bool = True,
    repair_config: bool = False,
) -> InitPlan:
    changes: list[InitPlanEntry] = []
    errors: list[str] = []
    config_path = paths.root / "pcl.yaml"
    repair_commands = _legacy_empty_config_commands(config_path) if repair_config else []

    if not _plan_dir(changes, errors, paths.root, paths.root, "target project root"):
        return InitPlan(root=paths.root, changes=changes, errors=errors)
    loop_dir_ok = _plan_dir(
        changes,
        errors,
        paths.root,
        paths.loop_dir,
        "project-loop local state directory",
    )
    if loop_dir_ok:
        for rel in DEFAULT_DIRS:
            _plan_dir(changes, errors, paths.root, paths.loop_dir / rel, "project-loop support directory")

    if paths.db_path.exists():
        if paths.db_path.is_dir():
            _plan_error(changes, errors, paths.root, paths.db_path, "expected SQLite database file but found a directory")
        else:
            pending_migration_ids = _pending_migration_ids(paths, changes, errors)
            if pending_migration_ids:
                changes.append(
                    InitPlanEntry(
                        action="update",
                        path=_display_path(paths.root, paths.db_path),
                        reason=f"would apply pending migrations: {', '.join(pending_migration_ids)}",
                    )
                )
            else:
                changes.append(
                    InitPlanEntry(
                        action="skip",
                        path=_display_path(paths.root, paths.db_path),
                        reason="local SQLite loop memory already exists and will be preserved",
                    )
                )
    else:
        if _blocking_file_ancestor(paths.root, paths.db_path) is None and loop_dir_ok:
            changes.append(
                InitPlanEntry(
                    action="create",
                    path=_display_path(paths.root, paths.db_path),
                    reason="create local SQLite loop memory",
                )
            )
    pending_migration_ids = _planned_pending_migrations(changes, paths.root, paths.db_path)
    event_update_reasons: list[str] = []
    if pending_migration_ids:
        event_update_reasons.append(f"would append migration events for: {', '.join(pending_migration_ids)}")
    if overwrite:
        event_update_reasons.append("would append project_initialized event")
    elif repair_commands:
        event_update_reasons.append("would append project_config_repaired event")
    if paths.events_path.exists() and paths.events_path.is_dir():
        _plan_error(changes, errors, paths.root, paths.events_path, "expected append-only audit log file but found a directory")
    elif paths.events_path.exists():
        changes.append(
            InitPlanEntry(
                action="update" if event_update_reasons else "skip",
                path=_display_path(paths.root, paths.events_path),
                reason="; ".join(event_update_reasons) if event_update_reasons else "append-only audit log already exists",
            )
        )
    elif _blocking_file_ancestor(paths.root, paths.events_path) is None and loop_dir_ok:
        changes.append(
            InitPlanEntry(
                action="create",
                path=_display_path(paths.root, paths.events_path),
                reason="create append-only audit log",
            )
        )
    _, detected_project = _project_config_text(paths.root)
    config_create_reason = "install project-loop configuration template"
    config_overwrite_reason = "would overwrite pcl.yaml from template"
    if detected_project is not None:
        detected_commands = ", ".join(detected_project["commands"])
        command_suffix = f" with commands: {detected_commands}" if detected_commands else ""
        config_create_reason = (
            "install project-loop configuration for detected "
            f"{detected_project['label']} project {detected_project['name']}{command_suffix}"
        )
        config_overwrite_reason = (
            "would overwrite pcl.yaml for detected "
            f"{detected_project['label']} project {detected_project['name']}{command_suffix}"
        )
    if repair_commands:
        changes.append(
            InitPlanEntry(
                action="update",
                path="pcl.yaml",
                reason=(
                    "normalize legacy empty command values to null: "
                    + ", ".join(repair_commands)
                ),
            )
        )
    else:
        _plan_file(
            changes,
            errors,
            paths.root,
            config_path,
            overwrite=overwrite,
            create_reason=config_create_reason,
            skip_reason=(
                "pcl.yaml has no legacy empty command values to repair"
                if repair_config and config_path.exists()
                else "pcl.yaml already exists"
            ),
            overwrite_reason=config_overwrite_reason,
        )

    _plan_resource_tree(
        changes,
        errors,
        paths.root,
        "templates/workflows",
        paths.workflows_dir,
        overwrite=overwrite,
        create_reason="install bundled workflow template",
        skip_reason="workflow template already exists",
        overwrite_reason="would overwrite workflow template",
    )
    _plan_resource_tree(
        changes,
        errors,
        paths.root,
        "templates/skills/project-control-loop",
        paths.agents_skill_dir,
        overwrite=overwrite,
        create_reason="install project-control-loop skill",
        skip_reason="project-control-loop skill file already exists",
        overwrite_reason="would overwrite project-control-loop skill file",
    )

    _plan_file(
        changes,
        errors,
        paths.root,
        paths.dashboard_html,
        overwrite=overwrite,
        create_reason="create initial generated dashboard shell",
        skip_reason="dashboard HTML already exists",
        overwrite_reason="would overwrite generated dashboard shell",
    )
    _plan_file(
        changes,
        errors,
        paths.root,
        paths.dashboard_data,
        overwrite=overwrite,
        create_reason="create initial dashboard data file",
        skip_reason="dashboard data already exists",
        overwrite_reason="would overwrite dashboard data file",
    )

    _plan_append_block(
        changes,
        errors,
        paths.root,
        paths.root / "AGENTS.md",
        marker="<!-- project-loop-harness:start -->",
        create_reason="create AGENTS.md with project-loop instructions",
        update_reason="append project-loop instructions to AGENTS.md",
        skip_reason="AGENTS.md already has project-loop instructions",
    )
    if with_claude:
        _plan_append_block(
            changes,
            errors,
            paths.root,
            paths.root / "CLAUDE.md",
            marker="<!-- project-loop-harness:start -->",
            create_reason="create CLAUDE.md with project-loop instructions",
            update_reason="append project-loop instructions to CLAUDE.md",
            skip_reason="CLAUDE.md already has project-loop instructions",
        )
    _plan_append_block(
        changes,
        errors,
        paths.root,
        paths.root / ".gitignore",
        marker="# Project Loop Harness local state",
        create_reason="create .gitignore with local-state exclusions",
        update_reason="append project-loop local-state exclusions to .gitignore",
        skip_reason=".gitignore already has project-loop local-state exclusions",
    )

    return InitPlan(root=paths.root, changes=changes, errors=errors)


def init_project(
    paths: ProjectPaths,
    *,
    overwrite: bool = False,
    with_claude: bool = True,
    repair_config: bool = False,
) -> InitResult:
    was_initialized = paths.db_path.exists()
    events_existed = paths.events_path.exists()
    pcl_yaml = paths.root / "pcl.yaml"
    repair_existing_config = repair_config and pcl_yaml.is_file()

    paths.root.mkdir(parents=True, exist_ok=True)
    paths.loop_dir.mkdir(parents=True, exist_ok=True)
    for rel in DEFAULT_DIRS:
        (paths.loop_dir / rel).mkdir(parents=True, exist_ok=True)

    initialize_database(paths.db_path, paths.events_path)
    if not paths.events_path.exists():
        paths.events_path.write_text("", encoding="utf-8")

    # Project config and templates
    if overwrite or not pcl_yaml.exists():
        config_text, _ = _project_config_text(paths.root)
        pcl_yaml.write_text(config_text, encoding="utf-8")
    repaired_config_commands: list[str] = []
    if repair_existing_config:
        repaired_config_commands = _repair_legacy_empty_config_commands(pcl_yaml)

    copy_tree_resource("templates/workflows", paths.workflows_dir, overwrite=overwrite)
    copy_tree_resource("templates/skills/project-control-loop", paths.agents_skill_dir, overwrite=overwrite)

    # Initial dashboard files
    if overwrite or not paths.dashboard_html.exists():
        paths.dashboard_html.write_text(read_text_resource("templates/dashboard/dashboard.html"), encoding="utf-8")
    if overwrite or not paths.dashboard_data.exists():
        paths.dashboard_data.write_text("{}\n", encoding="utf-8")

    # Agent instruction blocks
    append_block_once(
        paths.root / "AGENTS.md",
        "<!-- project-loop-harness:start -->",
        read_text_resource("templates/project/AGENTS.block.md"),
    )
    if with_claude:
        append_block_once(
            paths.root / "CLAUDE.md",
            "<!-- project-loop-harness:start -->",
            read_text_resource("templates/project/CLAUDE.block.md"),
        )

    # Local gitignore recommendations
    append_block_once(
        paths.root / ".gitignore",
        "# Project Loop Harness local state",
        read_text_resource("templates/project/gitignore.fragment"),
    )

    initialization_event = (not was_initialized) or overwrite or (not events_existed)
    event_appended = initialization_event or bool(repaired_config_commands)
    if event_appended:
        conn = connect_mutation(paths)
        try:
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type=(
                    "project_initialized" if initialization_event else "project_config_repaired"
                ),
                entity_type="project",
                entity_id="project",
                payload={
                    "root": str(paths.root),
                    "created": not was_initialized,
                    "force": overwrite,
                    "repaired_config_commands": repaired_config_commands,
                },
            )
            conn.commit()
        finally:
            conn.close()

    return InitResult(
        root=paths.root,
        created=not was_initialized,
        event_appended=event_appended,
        repaired_config_commands=tuple(repaired_config_commands),
    )


def _legacy_empty_config_commands(path: Path) -> list[str]:
    if not path.is_file():
        return []
    _, commands = _normalized_legacy_config(path.read_bytes())
    return commands


def _repair_legacy_empty_config_commands(path: Path) -> list[str]:
    original = path.read_bytes()
    repaired, commands = _normalized_legacy_config(original)
    if commands:
        path.write_bytes(repaired)
    return commands


def _normalized_legacy_config(content: bytes) -> tuple[bytes, list[str]]:
    text = content.decode("utf-8")
    lines = text.splitlines(keepends=True)
    repaired_commands: list[str] = []
    in_commands = False
    command_pattern = re.compile(
        r"^(?P<prefix>  (?P<key>install|lint|typecheck|test|e2e|build)\s*:\s*)"
        r"(?P<empty>\"\"|'')(?P<suffix>\s*(?:#.*)?)(?P<newline>\r?\n)?$"
    )
    for index, line in enumerate(lines):
        without_newline = line.rstrip("\r\n")
        if without_newline == "commands:":
            in_commands = True
            continue
        if in_commands and without_newline and not without_newline.startswith((" ", "\t")):
            in_commands = False
        if not in_commands:
            continue
        match = command_pattern.fullmatch(line)
        if match is None:
            continue
        lines[index] = (
            f"{match.group('prefix')}null{match.group('suffix')}"
            f"{match.group('newline') or ''}"
        )
        repaired_commands.append(match.group("key"))
    return "".join(lines).encode("utf-8"), repaired_commands


def _project_config_text(root: Path) -> tuple[str, dict[str, Any] | None]:
    template = read_text_resource("templates/project/pcl.yaml")
    package = _read_package_json(root / "package.json")
    if package is not None:
        raw_name = package.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            name = root.name or "CHANGE_ME"
        scripts = package.get("scripts")
        scripts = scripts if isinstance(scripts, dict) else {}
        command_keys = [
            key
            for key in VERIFICATION_COMMAND_KEYS
            if isinstance(scripts.get(key), str)
            and _is_supported_node_verification_script(scripts[key])
        ]
        package_runner = _node_package_runner(root, package)
        commands = {key: f"{package_runner} run {key}" for key in command_keys}
        config = _detected_config_text(
            template,
            name=name,
            project_type="node",
            commands=commands,
        )
        return config, {
            "name": name,
            "label": "Node",
            "commands": command_keys,
            "runner": package_runner,
        }

    python_project = _detect_python_project(root)
    if python_project is None:
        return template, None
    config = _detected_config_text(
        template,
        name=python_project["name"],
        project_type="python",
        commands=python_project["commands"],
    )
    return config, {
        "name": python_project["name"],
        "label": "Python",
        "commands": [
            key for key in VERIFICATION_COMMAND_KEYS if key in python_project["commands"]
        ],
    }


def _detected_config_text(
    template: str,
    *,
    name: str,
    project_type: str,
    commands: dict[str, str],
) -> str:
    config = template.replace('  name: "CHANGE_ME"', f"  name: {_yaml_string(name)}", 1)
    config = config.replace('  type: "generic"', f"  type: {_yaml_string(project_type)}", 1)
    for key in CONFIG_COMMAND_KEYS:
        config = config.replace(f'  {key}: ""', f"  {key}: null", 1)
    for key, command in commands.items():
        config = config.replace(f"  {key}: null", f"  {key}: {_yaml_string(command)}", 1)
    return config


def _detect_python_project(root: Path) -> dict[str, Any] | None:
    markers = (
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
    )
    if not any((root / marker).is_file() for marker in markers):
        return None

    pyproject_text = _read_text(root / "pyproject.toml")
    name = (
        _toml_section_string(pyproject_text, "project", "name")
        or _toml_section_string(pyproject_text, "tool.poetry", "name")
        or _setup_cfg_name(root / "setup.cfg")
        or root.name
        or "CHANGE_ME"
    )

    commands: dict[str, str] = {}
    if _python_tool_declared(root, pyproject_text, "ruff"):
        commands["lint"] = "ruff check ."
    if _python_tool_declared(root, pyproject_text, "mypy"):
        commands["typecheck"] = "python -m mypy ."
    if _python_tool_declared(root, pyproject_text, "pytest"):
        commands["test"] = "python -m pytest"
    return {"name": name, "commands": commands}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _toml_section_string(text: str, section: str, key: str) -> str:
    current_section = ""
    section_pattern = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")
    value_pattern = re.compile(
        rf"^\s*{re.escape(key)}\s*=\s*([\"'])(.*?)\1\s*(?:#.*)?$"
    )
    for line in text.splitlines():
        section_match = section_pattern.match(line)
        if section_match:
            current_section = section_match.group(1).strip()
            continue
        if current_section != section:
            continue
        value_match = value_pattern.match(line)
        if value_match:
            return value_match.group(2).strip()
    return ""


def _setup_cfg_name(path: Path) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as file:
            parser.read_file(file)
    except (OSError, UnicodeError, configparser.Error):
        return ""
    return parser.get("metadata", "name", fallback="").strip()


def _python_tool_declared(root: Path, pyproject_text: str, tool: str) -> bool:
    section_prefixes = {
        "ruff": ("[tool.ruff",),
        "mypy": ("[tool.mypy",),
        "pytest": ("[tool.pytest",),
    }
    lowered = pyproject_text.lower()
    if any(prefix in lowered for prefix in section_prefixes[tool]):
        return True
    dependency_pattern = re.compile(
        r'''["']'''
        + re.escape(tool)
        + r'''(?:\[[^"']*])?(?:[<>=!~][^"']*)?["']''',
        re.IGNORECASE,
    )
    if dependency_pattern.search(pyproject_text):
        return True

    config_files = {
        "ruff": ("ruff.toml", ".ruff.toml"),
        "mypy": ("mypy.ini", ".mypy.ini"),
        "pytest": ("pytest.ini", "conftest.py"),
    }
    if any((root / filename).is_file() for filename in config_files[tool]):
        return True
    return any(_requirements_declares_tool(path, tool) for path in root.glob("requirements*.txt"))


def _requirements_declares_tool(path: Path, tool: str) -> bool:
    text = _read_text(path)
    pattern = re.compile(
        rf"^{re.escape(tool)}(?:\[[^]]+])?(?:\s*[<>=!~].*)?$",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        line = raw_line.partition("#")[0].partition(";")[0].strip()
        if pattern.fullmatch(line):
            return True
    return False


def _read_package_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _node_package_runner(root: Path, package: dict[str, Any]) -> str:
    package_manager = package.get("packageManager")
    if isinstance(package_manager, str):
        runner = package_manager.partition("@")[0].strip()
        if runner in {"npm", "pnpm", "yarn", "bun"}:
            return runner
    lockfile_runners = (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lock", "bun"),
        ("bun.lockb", "bun"),
    )
    for lockfile, runner in lockfile_runners:
        if (root / lockfile).is_file():
            return runner
    return "npm"


def _is_supported_node_verification_script(script: str) -> bool:
    script = script.strip()
    if not script or any(fragment in script for fragment in ("||", ";", "|", "<", ">", "$(`", "$(", "`")):
        return False
    segments = [segment.strip() for segment in script.split("&&")]
    if not all(segments):
        return False
    for segment in segments:
        try:
            argv = shlex.split(segment)
        except ValueError:
            return False
        if not argv:
            return False
        executable = Path(argv[0]).name
        if executable == "node":
            if not _is_safe_node_verification_argv(argv):
                return False
        elif executable not in SAFE_NODE_SCRIPT_EXECUTABLES:
            return False
    return True


def _is_safe_node_verification_argv(argv: list[str]) -> bool:
    if len(argv) < 2 or argv[1] not in {"--check", "--test"}:
        return False
    operands = argv[2:]
    if argv[1] == "--check" and len(operands) != 1:
        return False
    for operand in operands:
        path = Path(operand)
        if operand.startswith("-") or path.is_absolute() or ".." in path.parts:
            return False
        if argv[1] == "--check" and path.suffix not in {".js", ".mjs", ".cjs"}:
            return False
    return True


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _plan_dir(changes: list[InitPlanEntry], errors: list[str], root: Path, path: Path, reason: str) -> bool:
    if path.exists():
        if path.is_dir():
            changes.append(InitPlanEntry(action="skip", path=_display_path(root, path), reason=reason))
            return True
        _plan_error(changes, errors, root, path, "expected directory but found a file")
        return False
    blocker = _blocking_file_ancestor(root, path)
    if blocker is not None:
        _plan_error(
            changes,
            errors,
            root,
            path,
            f"cannot create because {_display_path(root, blocker)} is not a directory",
        )
        return False
    changes.append(InitPlanEntry(action="create", path=_display_path(root, path), reason=reason))
    return True


def _plan_file(
    changes: list[InitPlanEntry],
    errors: list[str],
    root: Path,
    path: Path,
    *,
    overwrite: bool,
    create_reason: str,
    skip_reason: str,
    overwrite_reason: str,
) -> None:
    if path.exists():
        if path.is_dir():
            _plan_error(changes, errors, root, path, "expected file but found a directory")
            return
        action = "overwrite" if overwrite else "skip"
        reason = overwrite_reason if overwrite else skip_reason
    else:
        blocker = _blocking_file_ancestor(root, path)
        if blocker is not None:
            _plan_error(
                changes,
                errors,
                root,
                path,
                f"cannot create because {_display_path(root, blocker)} is not a directory",
            )
            return
        action = "create"
        reason = create_reason
    changes.append(InitPlanEntry(action=action, path=_display_path(root, path), reason=reason))


def _plan_resource_tree(
    changes: list[InitPlanEntry],
    errors: list[str],
    root: Path,
    relative_dir: str,
    destination: Path,
    *,
    overwrite: bool,
    create_reason: str,
    skip_reason: str,
    overwrite_reason: str,
) -> None:
    for rel in list_resource_files(relative_dir):
        _plan_file(
            changes,
            errors,
            root,
            destination / rel,
            overwrite=overwrite,
            create_reason=create_reason,
            skip_reason=skip_reason,
            overwrite_reason=overwrite_reason,
        )


def _plan_append_block(
    changes: list[InitPlanEntry],
    errors: list[str],
    root: Path,
    path: Path,
    *,
    marker: str,
    create_reason: str,
    update_reason: str,
    skip_reason: str,
) -> None:
    if not path.exists():
        blocker = _blocking_file_ancestor(root, path)
        if blocker is not None:
            _plan_error(
                changes,
                errors,
                root,
                path,
                f"cannot create because {_display_path(root, blocker)} is not a directory",
            )
            return
        action = "create"
        reason = create_reason
    elif path.is_dir():
        _plan_error(changes, errors, root, path, "expected file but found a directory")
        return
    else:
        text = path.read_text(encoding="utf-8")
        action = "skip" if marker in text else "update"
        reason = skip_reason if action == "skip" else update_reason
    changes.append(InitPlanEntry(action=action, path=_display_path(root, path), reason=reason))


def _pending_migration_ids(
    paths: ProjectPaths,
    changes: list[InitPlanEntry],
    errors: list[str],
) -> list[str]:
    try:
        status = migration_status(paths)
    except Exception as exc:
        _plan_error(
            changes,
            errors,
            paths.root,
            paths.db_path,
            f"could not inspect migration status: {exc}",
        )
        return []
    return [migration.id for migration in status.pending]


def _planned_pending_migrations(changes: list[InitPlanEntry], root: Path, db_path: Path) -> list[str]:
    db_display_path = _display_path(root, db_path)
    prefix = "would apply pending migrations: "
    for change in changes:
        if change.path == db_display_path and change.reason.startswith(prefix):
            return [value.strip() for value in change.reason.removeprefix(prefix).split(",") if value.strip()]
    return []


def _plan_error(
    changes: list[InitPlanEntry],
    errors: list[str],
    root: Path,
    path: Path,
    reason: str,
) -> None:
    display_path = _display_path(root, path)
    changes.append(InitPlanEntry(action="error", path=display_path, reason=reason))
    errors.append(f"{display_path}: {reason}")


def _blocking_file_ancestor(root: Path, path: Path) -> Path | None:
    current = path.parent
    while True:
        if current.exists() and not current.is_dir():
            return current
        if current == root or current == current.parent:
            return None
        current = current.parent


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix() or "."
    except ValueError:
        return str(path)
