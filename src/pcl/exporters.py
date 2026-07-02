from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .db import connect
from .guards import require_initialized
from .paths import ProjectPaths
from .workflow_proposals import list_workflow_proposals


EXPORT_TABLES: tuple[tuple[str, str], ...] = (
    ("metadata", "key"),
    ("schema_migrations", "version"),
    ("events", "rowid"),
    ("goals", "id"),
    ("workflows", "id"),
    ("workflow_runs", "id"),
    ("agent_jobs", "id"),
    ("features", "id"),
    ("user_stories", "id"),
    ("test_cases", "id"),
    ("tasks", "id"),
    ("task_dependencies", "task_id, depends_on_task_id"),
    ("evidence", "id"),
    ("defects", "id"),
    ("decisions", "id"),
    ("verifications", "id"),
    ("escalations", "id"),
)

WORKFLOW_PROPOSAL_FIELDS = [
    "id",
    "workflow_id",
    "path",
    "workflow_path",
    "status",
    "summary",
    "review_summary",
    "created_at",
    "reviewed_at",
    "content_sha256",
    "parse_error",
]


def export_csv(paths: ProjectPaths) -> list[Path]:
    require_initialized(paths)

    paths.exports_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(paths.db_path)
    written: list[Path] = []
    try:
        for table, order_by in EXPORT_TABLES:
            cursor = conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
            rows = [dict(row) for row in cursor.fetchall()]
            fields = [str(column[0]) for column in cursor.description]
            out = paths.exports_dir / f"{table}.csv"
            _write_csv(out, fields, rows)
            written.append(out)
    finally:
        conn.close()

    proposal_rows = [
        {field: proposal.get(field, "") for field in WORKFLOW_PROPOSAL_FIELDS}
        for proposal in list_workflow_proposals(paths, validate=False)
    ]
    proposal_out = paths.exports_dir / "workflow_proposals.csv"
    _write_csv(proposal_out, WORKFLOW_PROPOSAL_FIELDS, proposal_rows)
    written.append(proposal_out)
    return written


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
