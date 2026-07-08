from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pcl.migrations as migrations_module
from pcl.cli import main
from pcl.db import connect
from pcl.migrations import discover_migrations
from pcl.resources import read_text_resource


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_old_v1_db(root: Path) -> None:
    loop_dir = root / ".project-loop"
    loop_dir.mkdir(parents=True)
    conn = connect(loop_dir / "project.db")
    try:
        schema = read_text_resource("db/schema.sql")
        schema = schema.replace(
            """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
""",
            "",
        )
        conn.executescript(schema)
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("pcl_version", "0.1.0"),
        )
        conn.commit()
    finally:
        conn.close()
    (root / "pcl.yaml").write_text("project_loop:\n  version: \"0.1.0\"\n", encoding="utf-8")
    (root / ".agents" / "skills" / "project-control-loop").mkdir(parents=True)
    (root / ".agents" / "skills" / "project-control-loop" / "SKILL.md").write_text(
        "# Skill\n", encoding="utf-8"
    )


def _create_migrated_v1_db(root: Path) -> None:
    loop_dir = root / ".project-loop"
    loop_dir.mkdir(parents=True)
    migration_sql = read_text_resource("db/migrations/001_initial.sql")
    conn = connect(loop_dir / "project.db")
    try:
        conn.executescript(migration_sql)
        conn.execute(
            """
            INSERT INTO schema_migrations(version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (1, "initial", hashlib.sha256(migration_sql.encode("utf-8")).hexdigest(), "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("pcl_version", "0.1.0"),
        )
        conn.commit()
    finally:
        conn.close()
    (root / "pcl.yaml").write_text("project_loop:\n  version: \"0.1.0\"\n", encoding="utf-8")
    (root / ".agents" / "skills" / "project-control-loop").mkdir(parents=True)
    (root / ".agents" / "skills" / "project-control-loop" / "SKILL.md").write_text(
        "# Skill\n", encoding="utf-8"
    )


def _create_migrated_v2_db(root: Path) -> None:
    loop_dir = root / ".project-loop"
    loop_dir.mkdir(parents=True)
    migrations = [
        (1, "initial", read_text_resource("db/migrations/001_initial.sql")),
        (2, "tasks", read_text_resource("db/migrations/002_tasks.sql")),
    ]
    conn = connect(loop_dir / "project.db")
    try:
        for version, name, migration_sql in migrations:
            conn.executescript(migration_sql)
            conn.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    version,
                    name,
                    hashlib.sha256(migration_sql.encode("utf-8")).hexdigest(),
                    "2026-01-01T00:00:00Z",
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", "2"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("pcl_version", "0.1.0"),
        )
        conn.commit()
    finally:
        conn.close()
    (root / "pcl.yaml").write_text("project_loop:\n  version: \"0.1.0\"\n", encoding="utf-8")
    (root / ".agents" / "skills" / "project-control-loop").mkdir(parents=True)
    (root / ".agents" / "skills" / "project-control-loop" / "SKILL.md").write_text(
        "# Skill\n", encoding="utf-8"
    )


def _create_migrated_db_with_metadata(root: Path, *, schema_version: int, applied_through: int) -> None:
    loop_dir = root / ".project-loop"
    loop_dir.mkdir(parents=True)
    conn = connect(loop_dir / "project.db")
    try:
        for migration in migrations_module.discover_migrations():
            if migration.version > applied_through:
                continue
            conn.executescript(migration.sql)
            conn.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    "2026-07-05T00:01:42Z",
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("schema_version", str(schema_version)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("pcl_version", "0.1.0"),
        )
        conn.commit()
    finally:
        conn.close()
    (loop_dir / "events.jsonl").write_text("", encoding="utf-8")
    (root / "pcl.yaml").write_text("project_loop:\n  version: \"0.1.0\"\n", encoding="utf-8")
    (root / ".agents" / "skills" / "project-control-loop").mkdir(parents=True)
    (root / ".agents" / "skills" / "project-control-loop" / "SKILL.md").write_text(
        "# Skill\n", encoding="utf-8"
    )


def _create_migrated_v4_db_with_metadata(root: Path, schema_version: int = 4) -> None:
    _create_migrated_db_with_metadata(root, schema_version=schema_version, applied_through=4)


def _create_migrated_v5_db_with_metadata(root: Path, schema_version: int = 5) -> None:
    _create_migrated_db_with_metadata(root, schema_version=schema_version, applied_through=5)


def _create_migrated_v6_db_with_metadata(root: Path, schema_version: int = 6) -> None:
    _create_migrated_db_with_metadata(root, schema_version=schema_version, applied_through=6)


def _create_migrated_v7_db_with_metadata(root: Path, schema_version: int = 7) -> None:
    _create_migrated_db_with_metadata(root, schema_version=schema_version, applied_through=7)


def _schema_definitions(root: Path) -> list[tuple[str, str, str | None]]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        rows = conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger', 'view')
            ORDER BY type, name
            """
        ).fetchall()
        return [(str(row["type"]), str(row["name"]), row["sql"]) for row in rows]
    finally:
        conn.close()


def _metadata_schema_version(root: Path) -> str:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        return str(row["value"])
    finally:
        conn.close()


def test_discover_migrations() -> None:
    migrations = discover_migrations()

    assert [migration.id for migration in migrations] == [
        "001_initial",
        "002_tasks",
        "003_agent_registry",
        "004_code_index",
        "005_verification_feedback",
        "006_evidence_task_link",
        "007_evidence_links",
    ]
    assert all(migration.checksum for migration in migrations)


def test_init_records_latest_migration(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    payload = _json_output(capsys)
    assert payload["created"] is True

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        assert [dict(row) for row in rows] == [
            {"version": 1, "name": "initial"},
            {"version": 2, "name": "tasks"},
            {"version": 3, "name": "agent_registry"},
            {"version": 4, "name": "code_index"},
            {"version": 5, "name": "verification_feedback"},
            {"version": 6, "name": "evidence_task_link"},
            {"version": 7, "name": "evidence_links"},
        ]
        schema_version = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert schema_version["value"] == "7"
    finally:
        conn.close()


def test_migrate_status_reports_fresh_project_without_mutating(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    before_events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["applied_versions"] == [1, 2, 3, 4, 5, 6, 7]
    assert payload["pending"] == []
    assert payload["latest_version"] == 7
    assert payload["current_schema_version"] == 7
    assert payload["has_migrations_table"] is True
    assert payload["metadata_schema_version"] == 7
    assert payload["max_applied_version"] == 7
    assert payload["consistent"] is True
    assert payload["warnings"] == []
    assert (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8") == before_events


def test_migrate_status_flag_reports_without_mutating(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    before_events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")

    assert main(["--root", str(tmp_path), "migrate", "--status", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["applied_versions"] == [1, 2, 3, 4, 5, 6, 7]
    assert payload["pending"] == []
    assert payload["latest_version"] == 7
    assert payload["metadata_schema_version"] == 7
    assert payload["max_applied_version"] == 7
    assert payload["consistent"] is True
    assert payload["warnings"] == []
    assert (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8") == before_events


def test_migrate_status_reports_pending_old_db_without_applying(tmp_path: Path, capsys) -> None:
    _create_old_v1_db(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["ok"] is True
    assert payload["applied_versions"] == []
    assert [f"{migration['version']:03d}_{migration['name']}" for migration in payload["pending"]] == [
        "001_initial",
        "002_tasks",
        "003_agent_registry",
        "004_code_index",
        "005_verification_feedback",
        "006_evidence_task_link",
        "007_evidence_links",
    ]
    assert payload["latest_version"] == 7
    assert payload["current_schema_version"] == 1
    assert payload["has_migrations_table"] is False
    assert not (tmp_path / ".project-loop" / "events.jsonl").exists()


def test_old_db_without_migrations_table_can_be_upgraded(tmp_path: Path, capsys) -> None:
    _create_old_v1_db(tmp_path)

    assert main(["--root", str(tmp_path), "doctor", "--json"]) == 0
    doctor = _json_output(capsys)
    assert doctor["ok"] is True
    assert any(
        "Pending migrations: 001_initial, 002_tasks, 003_agent_registry, 004_code_index, "
        "005_verification_feedback, 006_evidence_task_link, 007_evidence_links" in warning
        for warning in doctor["warnings"]
    )

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json_output(capsys)
    assert [migration["version"] for migration in migrated["applied"]] == [1, 2, 3, 4, 5, 6, 7]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        assert [dict(row) for row in rows] == [
            {"version": 1, "name": "initial"},
            {"version": 2, "name": "tasks"},
            {"version": 3, "name": "agent_registry"},
            {"version": 4, "name": "code_index"},
            {"version": 5, "name": "verification_feedback"},
            {"version": 6, "name": "evidence_task_link"},
            {"version": 7, "name": "evidence_links"},
        ]
        task_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
        ).fetchone()
        index_runs_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'code_index_runs'"
        ).fetchone()
        index_files_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'code_index_files'"
        ).fetchone()
        feedback_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'verification_feedback'"
        ).fetchone()
        evidence_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(evidence)").fetchall()
        }
        assert task_table is not None
        assert index_runs_table is not None
        assert index_files_table is not None
        assert feedback_table is not None
        assert "linked_task_id" in evidence_columns
    finally:
        conn.close()

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "migration_applied" in events


def test_migrate_stamps_current_pcl_version_in_metadata(tmp_path: Path, capsys) -> None:
    import pcl

    _create_old_v1_db(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    _json_output(capsys)

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'pcl_version'"
        ).fetchone()
        assert row is not None
        assert row["value"] == pcl.__version__
        assert row["value"] != "0.1.0"
    finally:
        conn.close()


def test_existing_v1_database_with_migration_metadata_upgrades_to_007(tmp_path: Path, capsys) -> None:
    _create_migrated_v1_db(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["applied_versions"] == [1]
    assert [migration["version"] for migration in status["pending"]] == [2, 3, 4, 5, 6, 7]
    assert status["current_schema_version"] == 1

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json_output(capsys)
    assert [migration["version"] for migration in migrated["applied"]] == [2, 3, 4, 5, 6, 7]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        assert [dict(row) for row in rows] == [
            {"version": 1, "name": "initial"},
            {"version": 2, "name": "tasks"},
            {"version": 3, "name": "agent_registry"},
            {"version": 4, "name": "code_index"},
            {"version": 5, "name": "verification_feedback"},
            {"version": 6, "name": "evidence_task_link"},
            {"version": 7, "name": "evidence_links"},
        ]
        schema_version = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert schema_version["value"] == "7"
        task_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
        ).fetchone()
        dependency_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'task_dependencies'"
        ).fetchone()
        agents_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agents'"
        ).fetchone()
        index_runs_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'code_index_runs'"
        ).fetchone()
        index_files_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'code_index_files'"
        ).fetchone()
        feedback_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'verification_feedback'"
        ).fetchone()
        evidence_links_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'evidence_links'"
        ).fetchone()
        evidence_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(evidence)").fetchall()
        }
        assert task_table is not None
        assert dependency_table is not None
        assert agents_table is not None
        assert index_runs_table is not None
        assert index_files_table is not None
        assert feedback_table is not None
        assert evidence_links_table is not None
        assert "linked_task_id" in evidence_columns
    finally:
        conn.close()


def test_existing_v2_database_with_migration_metadata_upgrades_to_007(tmp_path: Path, capsys) -> None:
    _create_migrated_v2_db(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["applied_versions"] == [1, 2]
    assert [migration["version"] for migration in status["pending"]] == [3, 4, 5, 6, 7]
    assert status["current_schema_version"] == 2

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json_output(capsys)
    assert [migration["version"] for migration in migrated["applied"]] == [3, 4, 5, 6, 7]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        schema_version = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert schema_version["value"] == "7"
        agents_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agents'"
        ).fetchone()
        index_runs_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'code_index_runs'"
        ).fetchone()
        index_files_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'code_index_files'"
        ).fetchone()
        feedback_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'verification_feedback'"
        ).fetchone()
        evidence_links_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'evidence_links'"
        ).fetchone()
        evidence_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(evidence)").fetchall()
        }
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(agent_jobs)").fetchall()
        }
        assert agents_table is not None
        assert index_runs_table is not None
        assert index_files_table is not None
        assert feedback_table is not None
        assert evidence_links_table is not None
        assert "linked_task_id" in evidence_columns
        assert {
            "assigned_agent_id",
            "lease_expires_at",
            "last_heartbeat_at",
            "attempts",
        } <= columns
    finally:
        conn.close()


def test_existing_v4_database_with_migration_metadata_upgrades_to_007(tmp_path: Path, capsys) -> None:
    _create_migrated_v4_db_with_metadata(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["applied_versions"] == [1, 2, 3, 4]
    assert [migration["version"] for migration in status["pending"]] == [5, 6, 7]
    assert status["current_schema_version"] == 4

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json_output(capsys)
    assert [migration["version"] for migration in migrated["applied"]] == [5, 6, 7]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        schema_version = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert schema_version["value"] == "7"
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'verification_feedback'"
        ).fetchone()
        assert table_sql["sql"] == """CREATE TABLE verification_feedback (
  id TEXT PRIMARY KEY,
  suggestion_id TEXT NOT NULL,
  receipt_evidence_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('executed', 'skipped', 'not_applicable')),
  result TEXT CHECK(result IN ('passed', 'failed', 'inconclusive')),
  supporting_evidence_id TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  CHECK(
    (status = 'executed' AND result IS NOT NULL AND supporting_evidence_id IS NOT NULL)
    OR (status != 'executed' AND result IS NULL)
  ),
  FOREIGN KEY(receipt_evidence_id) REFERENCES evidence(id),
  FOREIGN KEY(supporting_evidence_id) REFERENCES evidence(id)
)"""
        rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        assert [dict(row) for row in rows] == [
            {"version": 1, "name": "initial"},
            {"version": 2, "name": "tasks"},
            {"version": 3, "name": "agent_registry"},
            {"version": 4, "name": "code_index"},
            {"version": 5, "name": "verification_feedback"},
            {"version": 6, "name": "evidence_task_link"},
            {"version": 7, "name": "evidence_links"},
        ]
        columns = {
            str(row["name"]): {
                "type": str(row["type"]),
                "notnull": int(row["notnull"]),
                "pk": int(row["pk"]),
            }
            for row in conn.execute("PRAGMA table_info(verification_feedback)").fetchall()
        }
        assert columns == {
            "id": {"type": "TEXT", "notnull": 0, "pk": 1},
            "suggestion_id": {"type": "TEXT", "notnull": 1, "pk": 0},
            "receipt_evidence_id": {"type": "TEXT", "notnull": 1, "pk": 0},
            "status": {"type": "TEXT", "notnull": 1, "pk": 0},
            "result": {"type": "TEXT", "notnull": 0, "pk": 0},
            "supporting_evidence_id": {"type": "TEXT", "notnull": 0, "pk": 0},
            "note": {"type": "TEXT", "notnull": 0, "pk": 0},
            "created_at": {"type": "TEXT", "notnull": 1, "pk": 0},
        }
        indexes = conn.execute("PRAGMA index_list(verification_feedback)").fetchall()
        assert [str(row["origin"]) for row in indexes] == ["pk"]
        fks = {
            (str(row["from"]), str(row["table"]), str(row["to"]))
            for row in conn.execute("PRAGMA foreign_key_list(verification_feedback)").fetchall()
        }
        assert fks == {
            ("receipt_evidence_id", "evidence", "id"),
            ("supporting_evidence_id", "evidence", "id"),
        }
        evidence_columns = {
            str(row["name"]): {
                "type": str(row["type"]),
                "notnull": int(row["notnull"]),
                "pk": int(row["pk"]),
            }
            for row in conn.execute("PRAGMA table_info(evidence)").fetchall()
        }
        assert evidence_columns["linked_task_id"] == {"type": "TEXT", "notnull": 0, "pk": 0}
        evidence_fks = {
            (str(row["from"]), str(row["table"]), str(row["to"]))
            for row in conn.execute("PRAGMA foreign_key_list(evidence)").fetchall()
        }
        assert ("linked_task_id", "tasks", "id") in evidence_fks
        evidence_indexes = {
            str(row["name"])
            for row in conn.execute("PRAGMA index_list(evidence)").fetchall()
        }
        assert "idx_evidence_linked_task" in evidence_indexes
        evidence_link_columns = {
            str(row["name"]): {
                "type": str(row["type"]),
                "notnull": int(row["notnull"]),
                "pk": int(row["pk"]),
            }
            for row in conn.execute("PRAGMA table_info(evidence_links)").fetchall()
        }
        assert evidence_link_columns == {
            "evidence_id": {"type": "TEXT", "notnull": 1, "pk": 1},
            "target_type": {"type": "TEXT", "notnull": 1, "pk": 2},
            "target_id": {"type": "TEXT", "notnull": 1, "pk": 3},
            "link_role": {"type": "TEXT", "notnull": 1, "pk": 4},
            "created_at": {"type": "TEXT", "notnull": 1, "pk": 0},
        }
        evidence_link_fks = {
            (str(row["from"]), str(row["table"]), str(row["to"]))
            for row in conn.execute("PRAGMA foreign_key_list(evidence_links)").fetchall()
        }
        assert evidence_link_fks == {("evidence_id", "evidence", "id")}
        evidence_link_indexes = {
            str(row["name"])
            for row in conn.execute("PRAGMA index_list(evidence_links)").fetchall()
        }
        assert "idx_evidence_links_target" in evidence_link_indexes
    finally:
        conn.close()


def test_evidence_links_migration_backfills_task_links_idempotently(
    tmp_path: Path,
    capsys,
) -> None:
    _create_migrated_v6_db_with_metadata(tmp_path)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO tasks(id, title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("T-0001", "Backfill target", "todo", "2026-07-08T00:00:00Z", "2026-07-08T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at, linked_task_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "E-0001",
                "adhoc_artifact",
                "inline:old-linked",
                "Old linked evidence",
                "2026-07-08T00:01:00Z",
                "T-0001",
            ),
        )
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, summary, created_at, linked_task_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "E-0002",
                "adhoc_artifact",
                "inline:unlinked",
                "Unlinked evidence",
                "2026-07-08T00:02:00Z",
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    first = _json_output(capsys)
    assert [migration["version"] for migration in first["applied"]] == [7]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        linked_count = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence WHERE linked_task_id IS NOT NULL"
        ).fetchone()["n"]
        link_rows = conn.execute(
            """
            SELECT evidence_id, target_type, target_id, link_role, created_at
            FROM evidence_links
            ORDER BY evidence_id
            """
        ).fetchall()
        assert linked_count == 1
        assert [dict(row) for row in link_rows] == [
            {
                "evidence_id": "E-0001",
                "target_type": "task",
                "target_id": "T-0001",
                "link_role": "supporting",
                "created_at": "2026-07-08T00:01:00Z",
            }
        ]
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    second = _json_output(capsys)
    assert second["applied"] == []
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row_count = conn.execute("SELECT COUNT(*) AS n FROM evidence_links").fetchone()["n"]
        assert row_count == 1
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path, capsys) -> None:
    _create_old_v1_db(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    first = _json_output(capsys)
    assert len(first["applied"]) == 7

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    second = _json_output(capsys)
    assert second["applied"] == []
    assert second["pending_before"] == []

    events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert events.count("migration_applied") == 7


def test_metadata_schema_version_behind_applied_is_diagnosed_and_repaired(
    tmp_path: Path,
    capsys,
) -> None:
    _create_migrated_v7_db_with_metadata(tmp_path, schema_version=5)
    before_schema = _schema_definitions(tmp_path)

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["applied_versions"] == [1, 2, 3, 4, 5, 6, 7]
    assert status["pending"] == []
    assert status["current_schema_version"] == 5
    assert status["metadata_schema_version"] == 5
    assert status["max_applied_version"] == 7
    assert status["consistent"] is False
    assert any(
        "metadata.schema_version 5 is behind applied migration 7" in warning
        and f"pcl migrate --root {tmp_path}" in warning
        for warning in status["warnings"]
    )

    assert main(["--root", str(tmp_path), "validate", "--json"]) == 0
    validate = _json_output(capsys)
    assert validate["ok"] is True
    assert any(
        "metadata.schema_version 5 is behind applied migration 7" in warning
        and f"pcl migrate --root {tmp_path}" in warning
        for warning in validate["warnings"]
    )

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    strict = _json_output(capsys)
    assert strict["ok"] is False
    assert any(
        "metadata.schema_version 5 is behind applied migration 7" in error
        and f"pcl migrate --root {tmp_path}" in error
        for error in strict["errors"]
    )

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 0
    migrated = _json_output(capsys)
    assert migrated["applied"] == []
    assert migrated["pending_before"] == []
    assert migrated["metadata_repaired"] is True
    assert migrated["metadata_repair"] == {
        "from_schema_version": 5,
        "to_schema_version": 7,
        "reason": "metadata.schema_version was behind schema_migrations; no DDL was run",
        "schema_migration_applied": False,
    }
    assert _schema_definitions(tmp_path) == before_schema
    assert _metadata_schema_version(tmp_path) == "7"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        migration_rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        repair_events = conn.execute(
            "SELECT event_type, payload_json FROM events WHERE event_type = ?",
            ("schema_metadata_repaired",),
        ).fetchall()
        assert [int(row["version"]) for row in migration_rows] == [1, 2, 3, 4, 5, 6, 7]
        assert len(repair_events) == 1
        assert "no DDL was run" in str(repair_events[0]["payload_json"])
    finally:
        conn.close()
    events_jsonl = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")
    assert "schema_metadata_repaired" in events_jsonl

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    repaired_status = _json_output(capsys)
    assert repaired_status["metadata_schema_version"] == 7
    assert repaired_status["max_applied_version"] == 7
    assert repaired_status["consistent"] is True
    assert repaired_status["warnings"] == []

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    clean_validate = _json_output(capsys)
    assert clean_validate["ok"] is True
    assert clean_validate["errors"] == []
    assert clean_validate["warnings"] == []


def test_migrate_refuses_database_ahead_of_running_binary(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_migrated_v7_db_with_metadata(tmp_path, schema_version=7)
    actual_migrations = migrations_module.discover_migrations()
    monkeypatch.setattr(migrations_module, "discover_migrations", lambda: actual_migrations[:6])
    before_events = (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8")

    assert main(["--root", str(tmp_path), "migrate", "status", "--json"]) == 0
    status = _json_output(capsys)
    assert status["latest_version"] == 6
    assert status["metadata_schema_version"] == 7
    assert status["max_applied_version"] == 7
    assert status["consistent"] is False
    assert any("unknown to this pcl binary" in warning for warning in status["warnings"])

    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 4
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "schema_version_ahead"
    assert "Database schema version 7 is ahead" in payload["error"]["message"]
    assert "latest migration 6" in payload["error"]["message"]
    assert payload["error"]["details"]["latest_version"] == 6
    assert payload["error"]["details"]["metadata_schema_version"] == 7
    assert payload["error"]["details"]["max_applied_version"] == 7
    assert payload["error"]["details"]["unknown_applied_versions"] == [7]
    assert _metadata_schema_version(tmp_path) == "7"
    assert (tmp_path / ".project-loop" / "events.jsonl").read_text(encoding="utf-8") == before_events


def test_migrate_before_init_fails(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "migrate", "--json"]) == 3
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "not_initialized"
