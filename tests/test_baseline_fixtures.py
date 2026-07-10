from __future__ import annotations

import json
from pathlib import Path
import shutil

from pcl.cli import main
from pcl.db import connect

from baseline_fixture_tools import generate_snapshot_fixtures, snapshot_bytes


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "v0.3.1-baseline"
SNAPSHOT_ROOT = FIXTURE_ROOT / "snapshots"
V030_DATABASE = FIXTURE_ROOT / "db" / "v0.3.0-schema-7.sqlite3"


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_baseline_snapshots_are_reproducible_and_committed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_snapshot_fixtures(first)
    generate_snapshot_fixtures(second)

    first_snapshots = snapshot_bytes(first)
    second_snapshots = snapshot_bytes(second)
    assert first_snapshots == second_snapshots
    committed = snapshot_bytes(SNAPSHOT_ROOT)
    assert {
        name: content for name, content in first_snapshots.items() if name != "pcl-help.json"
    } == {name: content for name, content in committed.items() if name != "pcl-help.json"}
    assert b"audit" in first_snapshots["pcl-help.json"]
    assert b"audit" not in committed["pcl-help.json"]


def test_v030_fixture_database_migrates_to_current_schema(tmp_path: Path, capsys) -> None:
    loop_dir = tmp_path / ".project-loop"
    loop_dir.mkdir()
    shutil.copyfile(V030_DATABASE, loop_dir / "project.db")

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    before = _json_output(capsys)
    assert before["current_schema_version"] == 7
    assert before["metadata_schema_version"] == 7
    assert before["applied_versions"] == [1, 2, 3, 4, 5, 6, 7]
    assert [migration["version"] for migration in before["pending"]] == [8]
    assert before["consistent"] is True

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json_output(capsys)
    assert [migration["version"] for migration in migrated["applied"]] == [8]
    assert [migration["version"] for migration in migrated["pending_before"]] == [8]
    assert migrated["latest_version"] == 8

    conn = connect(loop_dir / "project.db")
    try:
        metadata = {
            str(row["key"]): str(row["value"])
            for row in conn.execute(
                "SELECT key, value FROM metadata WHERE key IN ('pcl_version', 'schema_version')"
            ).fetchall()
        }
        table_names = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        domain_row_count = sum(
            int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
            for table_name in (
                "goals",
                "features",
                "user_stories",
                "test_cases",
                "tasks",
                "evidence",
            )
        )
    finally:
        conn.close()

    assert metadata["schema_version"] == "8"
    assert {"evidence_links", "verification_feedback", "code_index_runs", "outbox_records"}.issubset(table_names)
    assert domain_row_count == 0
