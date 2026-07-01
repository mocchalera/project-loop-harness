from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import initialize_database
from .db import connect
from .events import append_event
from .paths import ProjectPaths
from .resources import copy_tree_resource, read_text_resource


DEFAULT_DIRS = [
    "goals",
    "workflows",
    "workflow-proposals",
    "dashboard",
    "evidence/agent-runs",
    "evidence/test-results",
    "evidence/command-logs",
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


def append_block_once(path: Path, marker: str, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in existing:
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "\n" + block.strip() + "\n", encoding="utf-8")


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
        conn = connect(paths.db_path)
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
