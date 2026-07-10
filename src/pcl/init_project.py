from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class InitResult:
    root: Path
    created: bool
    event_appended: bool


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


def plan_init_project(paths: ProjectPaths, *, overwrite: bool = False, with_claude: bool = True) -> InitPlan:
    changes: list[InitPlanEntry] = []
    errors: list[str] = []

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
    _plan_file(
        changes,
        errors,
        paths.root,
        paths.root / "pcl.yaml",
        overwrite=overwrite,
        create_reason="install project-loop configuration template",
        skip_reason="pcl.yaml already exists",
        overwrite_reason="would overwrite pcl.yaml from template",
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


def init_project(paths: ProjectPaths, *, overwrite: bool = False, with_claude: bool = True) -> InitResult:
    was_initialized = paths.db_path.exists()
    events_existed = paths.events_path.exists()

    paths.root.mkdir(parents=True, exist_ok=True)
    paths.loop_dir.mkdir(parents=True, exist_ok=True)
    for rel in DEFAULT_DIRS:
        (paths.loop_dir / rel).mkdir(parents=True, exist_ok=True)

    initialize_database(paths.db_path, paths.events_path)
    if not paths.events_path.exists():
        paths.events_path.write_text("", encoding="utf-8")

    # Project config and templates
    pcl_yaml = paths.root / "pcl.yaml"
    if overwrite or not pcl_yaml.exists():
        pcl_yaml.write_text(read_text_resource("templates/project/pcl.yaml"), encoding="utf-8")

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

    event_appended = (not was_initialized) or overwrite or (not events_existed)
    if event_appended:
        conn = connect_mutation(paths)
        try:
            append_event(
                conn=conn,
                events_path=paths.events_path,
                event_type="project_initialized",
                entity_type="project",
                entity_id="project",
                payload={
                    "root": str(paths.root),
                    "created": not was_initialized,
                    "force": overwrite,
                },
            )
            conn.commit()
        finally:
            conn.close()

    return InitResult(root=paths.root, created=not was_initialized, event_appended=event_appended)


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
