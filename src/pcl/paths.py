from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def loop_dir(self) -> Path:
        return self.root / ".project-loop"

    @property
    def db_path(self) -> Path:
        return self.loop_dir / "project.db"

    @property
    def events_path(self) -> Path:
        return self.loop_dir / "events.jsonl"

    @property
    def dashboard_dir(self) -> Path:
        return self.loop_dir / "dashboard"

    @property
    def dashboard_html(self) -> Path:
        return self.dashboard_dir / "dashboard.html"

    @property
    def dashboard_data(self) -> Path:
        return self.dashboard_dir / "dashboard-data.json"

    @property
    def exports_dir(self) -> Path:
        return self.loop_dir / "exports"

    @property
    def reports_dir(self) -> Path:
        return self.loop_dir / "reports"

    @property
    def evidence_dir(self) -> Path:
        return self.loop_dir / "evidence"

    @property
    def context_receipts_dir(self) -> Path:
        return self.evidence_dir / "context-receipts"

    @property
    def workflows_dir(self) -> Path:
        return self.loop_dir / "workflows"

    @property
    def workflow_proposals_dir(self) -> Path:
        return self.loop_dir / "workflow-proposals"

    @property
    def goals_dir(self) -> Path:
        return self.loop_dir / "goals"

    @property
    def agents_skill_dir(self) -> Path:
        return self.root / ".agents" / "skills" / "project-control-loop"


def resolve_paths(root: str | Path | None = None) -> ProjectPaths:
    return ProjectPaths(root=Path(root or ".").resolve())
