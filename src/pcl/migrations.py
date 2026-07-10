from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from importlib import resources
from pathlib import Path
import sqlite3

from . import __version__ as PCL_VERSION
from .db import connect, get_metadata, table_exists
from .errors import DataStoreError, ProjectNotInitializedError
from .events import append_event
from .locks import project_operation_lock
from .outbox import ProjectionResult, project_pending_events
from .paths import ProjectPaths
from .timeutil import utc_now_iso


MIGRATION_RE = re.compile(r"^(?P<version>\d{3,})_(?P<name>[a-zA-Z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    filename: str
    sql: str
    checksum: str

    @property
    def id(self) -> str:
        return f"{self.version:03d}_{self.name}"

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "name": self.name,
            "filename": self.filename,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class MigrationResult:
    applied: list[Migration]
    pending_before: list[Migration]
    latest_version: int
    metadata_repair: dict[str, object] | None = None
    projection: ProjectionResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "applied": [migration.to_dict() for migration in self.applied],
            "pending_before": [migration.to_dict() for migration in self.pending_before],
            "latest_version": self.latest_version,
            "metadata_repaired": self.metadata_repair is not None,
            "metadata_repair": self.metadata_repair,
            "projection": self.projection.to_dict() if self.projection is not None else None,
        }


@dataclass(frozen=True)
class MigrationStatus:
    applied_versions: list[int]
    pending: list[Migration]
    latest_version: int
    current_schema_version: int | None
    has_migrations_table: bool
    metadata_schema_version: int | None
    max_applied_version: int | None
    consistent: bool
    warnings: list[str]
    unknown_applied_versions: list[int]

    def to_dict(self) -> dict[str, object]:
        return {
            "applied_versions": self.applied_versions,
            "pending": [migration.to_dict() for migration in self.pending],
            "latest_version": self.latest_version,
            "current_schema_version": self.current_schema_version,
            "has_migrations_table": self.has_migrations_table,
            "metadata_schema_version": self.metadata_schema_version,
            "max_applied_version": self.max_applied_version,
            "consistent": self.consistent,
            "warnings": self.warnings,
        }

    @property
    def is_ahead_of_binary(self) -> bool:
        return bool(self.unknown_applied_versions) or (
            self.metadata_schema_version is not None
            and self.metadata_schema_version > self.latest_version
        )

    @property
    def repairable_metadata(self) -> bool:
        return (
            not self.pending
            and not self.is_ahead_of_binary
            and self.metadata_schema_version is not None
            and self.max_applied_version is not None
            and self.metadata_schema_version < self.max_applied_version
        )


class SchemaVersionAheadError(DataStoreError):
    def __init__(self, *, status: MigrationStatus) -> None:
        ahead_version = max(
            [
                version
                for version in [
                    status.metadata_schema_version,
                    status.max_applied_version,
                    *status.unknown_applied_versions,
                ]
                if version is not None
            ],
            default=status.latest_version,
        )
        super().__init__(
            message=(
                f"Database schema version {ahead_version} is ahead of this pcl binary's "
                f"latest migration {status.latest_version}. Upgrade pcl before running "
                "`pcl migrate`."
            ),
            details={
                "latest_version": status.latest_version,
                "metadata_schema_version": status.metadata_schema_version,
                "max_applied_version": status.max_applied_version,
                "unknown_applied_versions": status.unknown_applied_versions,
            },
        )
        self.code = "schema_version_ahead"


def discover_migrations() -> list[Migration]:
    migration_dir = resources.files("pcl").joinpath("db/migrations")
    migrations: list[Migration] = []
    seen_versions: set[int] = set()
    for item in sorted(migration_dir.iterdir(), key=lambda path: path.name):
        if not item.is_file() or not item.name.endswith(".sql"):
            continue
        match = MIGRATION_RE.match(item.name)
        if match is None:
            raise DataStoreError(
                f"Invalid migration filename: {item.name}",
                details={"filename": item.name},
            )
        version = int(match.group("version"))
        if version in seen_versions:
            raise DataStoreError(
                f"Duplicate migration version: {version:03d}",
                details={"version": version},
            )
        seen_versions.add(version)
        sql = item.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                filename=item.name,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    return migrations


def latest_schema_version() -> int:
    migrations = discover_migrations()
    return max((migration.version for migration in migrations), default=0)


def ensure_schema_migrations_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
        """
    )


def _applied_versions(conn) -> list[int]:
    if not table_exists(conn, "schema_migrations"):
        return []
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row["version"]) for row in rows]


def _schema_version(conn) -> int | None:
    if not table_exists(conn, "metadata"):
        return None
    raw = get_metadata(conn, "schema_version")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise DataStoreError(
            f"Invalid metadata.schema_version: {raw}",
            details={"schema_version": raw},
        ) from exc


def _format_version(version: int) -> str:
    return f"{version:03d}"


def _build_consistency_warnings(
    *,
    root: object,
    metadata_schema_version: int | None,
    max_applied_version: int | None,
    latest_version: int,
    has_migrations_table: bool,
    unknown_applied_versions: list[int],
) -> list[str]:
    warnings: list[str] = []
    repair_command = f"pcl migrate --root {root}"
    if metadata_schema_version is None:
        warnings.append("Missing metadata.schema_version.")
    if unknown_applied_versions:
        latest_label = _format_version(latest_version)
        unknown = ", ".join(_format_version(version) for version in unknown_applied_versions)
        warnings.append(
            f"Database has applied migration(s) {unknown} unknown to this pcl binary "
            f"(latest known migration {latest_label}). Upgrade pcl before running `pcl migrate`."
        )
    if metadata_schema_version is not None and metadata_schema_version > latest_version:
        warnings.append(
            f"metadata.schema_version {metadata_schema_version} is ahead of this pcl binary's "
            f"latest migration {latest_version}. Upgrade pcl before running `pcl migrate`."
        )
    if (
        has_migrations_table
        and metadata_schema_version is not None
        and max_applied_version is not None
    ):
        if metadata_schema_version < max_applied_version:
            warnings.append(
                f"metadata.schema_version {metadata_schema_version} is behind applied "
                f"migration {max_applied_version}. Run `{repair_command}` to repair "
                "metadata without applying DDL."
            )
        elif metadata_schema_version > max_applied_version:
            warnings.append(
                f"metadata.schema_version {metadata_schema_version} is ahead of applied "
                f"migration {max_applied_version}; inspect migration state before applying changes."
            )
    return warnings


def _migration_status_for_conn(
    *,
    conn,
    paths: ProjectPaths,
    migrations: list[Migration],
) -> MigrationStatus:
    latest = max((migration.version for migration in migrations), default=0)
    known_versions = {migration.version for migration in migrations}
    has_table = table_exists(conn, "schema_migrations")
    applied_versions = _applied_versions(conn)
    applied_set = set(applied_versions)
    pending = [migration for migration in migrations if migration.version not in applied_set]
    metadata_schema_version = _schema_version(conn)
    max_applied_version = max(applied_versions, default=None)
    unknown_applied_versions = [version for version in applied_versions if version not in known_versions]
    warnings = _build_consistency_warnings(
        root=paths.root,
        metadata_schema_version=metadata_schema_version,
        max_applied_version=max_applied_version,
        latest_version=latest,
        has_migrations_table=has_table,
        unknown_applied_versions=unknown_applied_versions,
    )
    return MigrationStatus(
        applied_versions=applied_versions,
        pending=pending,
        latest_version=latest,
        current_schema_version=metadata_schema_version,
        has_migrations_table=has_table,
        metadata_schema_version=metadata_schema_version,
        max_applied_version=max_applied_version,
        consistent=not warnings,
        warnings=warnings,
        unknown_applied_versions=unknown_applied_versions,
    )


def migration_status(paths: ProjectPaths) -> MigrationStatus:
    migrations = discover_migrations()
    conn = connect(paths.db_path)
    try:
        return _migration_status_for_conn(conn=conn, paths=paths, migrations=migrations)
    finally:
        conn.close()


def apply_migrations(paths: ProjectPaths) -> MigrationResult:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))

    migrations = discover_migrations()
    latest = max((migration.version for migration in migrations), default=0)
    projection: ProjectionResult | None = None
    with project_operation_lock(paths.loop_dir, exclusive=True):
        conn = connect(paths.db_path)
        try:
            status = _migration_status_for_conn(conn=conn, paths=paths, migrations=migrations)
            if status.is_ahead_of_binary:
                raise SchemaVersionAheadError(status=status)
            pending = status.pending
            legacy_delivered_ids: set[str] = set()
            if any(migration.version == 8 for migration in pending) and table_exists(conn, "events"):
                legacy_delivered_ids = _preflight_legacy_jsonl(conn, paths.events_path)

            conn.execute("BEGIN IMMEDIATE")
            try:
                ensure_schema_migrations_table(conn)
                applied: list[Migration] = []
                for migration in pending:
                    _execute_sql_script(conn, migration.sql)
                    ensure_schema_migrations_table(conn)
                    conn.execute(
                        """
                        INSERT INTO schema_migrations(version, name, checksum, applied_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (migration.version, migration.name, migration.checksum, utc_now_iso()),
                    )
                    if table_exists(conn, "metadata"):
                        conn.execute(
                            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                            ("schema_version", str(migration.version)),
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                            ("pcl_version", PCL_VERSION),
                        )
                    if migration.version == 8:
                        _backfill_legacy_outbox(conn, legacy_delivered_ids)
                    applied.append(migration)

                if pending and table_exists(conn, "outbox_records"):
                    for migration in pending:
                        append_event(
                            conn=conn,
                            events_path=paths.events_path,
                            event_type="migration_applied",
                            entity_type="system",
                            entity_id=f"migration:{migration.id}",
                            payload={
                                "version": migration.version,
                                "name": migration.name,
                                "filename": migration.filename,
                                "checksum": migration.checksum,
                            },
                        )

                repair: dict[str, object] | None = None
                status_after = _migration_status_for_conn(conn=conn, paths=paths, migrations=migrations)
                if status_after.repairable_metadata:
                    from_version = status_after.metadata_schema_version
                    to_version = status_after.max_applied_version
                    conn.execute(
                        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                        ("schema_version", str(to_version)),
                    )
                    repair = {
                        "from_schema_version": from_version,
                        "to_schema_version": to_version,
                        "reason": (
                            "metadata.schema_version was behind schema_migrations; no DDL was run"
                        ),
                        "schema_migration_applied": False,
                    }
                    if table_exists(conn, "outbox_records"):
                        append_event(
                            conn=conn,
                            events_path=paths.events_path,
                            event_type="schema_metadata_repaired",
                            entity_type="system",
                            entity_id="metadata:schema_version",
                            payload=repair,
                        )
                elif latest and table_exists(conn, "metadata"):
                    current_metadata = _schema_version(conn)
                    applied_max = max(_applied_versions(conn), default=None)
                    stamp_version = max(
                        version
                        for version in [latest, current_metadata, applied_max]
                        if version is not None
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                        ("schema_version", str(stamp_version)),
                    )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    if pending or repair is not None:
        projection = project_pending_events(paths)
    return MigrationResult(
        applied=applied,
        pending_before=pending,
        latest_version=latest,
        metadata_repair=repair,
        projection=projection,
    )


def _execute_sql_script(conn: sqlite3.Connection, sql: str) -> None:
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if not sqlite3.complete_statement(statement):
            continue
        stripped = statement.strip()
        statement = ""
        if not stripped:
            continue
        if stripped.upper().startswith("PRAGMA FOREIGN_KEYS"):
            continue
        conn.execute(stripped)
    if statement.strip():
        raise DataStoreError("Migration contains an incomplete SQL statement.")


def _preflight_legacy_jsonl(conn: sqlite3.Connection, events_path: Path) -> set[str]:
    db_rows = conn.execute(
        """
        SELECT id, event_type, entity_type, entity_id, payload_json, created_at
        FROM events ORDER BY rowid
        """
    ).fetchall()
    if not events_path.exists():
        return set()
    try:
        raw = events_path.read_bytes()
    except OSError as exc:
        raise DataStoreError(
            "Could not read legacy events.jsonl before migration.",
            details={"path": str(events_path), "error": str(exc)},
        ) from exc
    if raw and not raw.endswith(b"\n"):
        raise DataStoreError("Legacy events.jsonl has a partial trailing line; migration refused.")
    jsonl_rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(raw.splitlines(), start=1):
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DataStoreError(
                f"Legacy events.jsonl line {line_number} is malformed; migration refused."
            ) from exc
        if not isinstance(value, dict) or not value.get("id"):
            raise DataStoreError(
                f"Legacy events.jsonl line {line_number} is an unknown record; migration refused."
            )
        event_id = str(value["id"])
        if event_id in seen_ids:
            raise DataStoreError(
                f"Legacy events.jsonl contains duplicate event id {event_id}; migration refused."
            )
        seen_ids.add(event_id)
        jsonl_rows.append(value)
    if len(jsonl_rows) > len(db_rows):
        raise DataStoreError("Legacy events.jsonl contains events absent from SQLite; migration refused.")

    delivered: set[str] = set()
    for position, value in enumerate(jsonl_rows):
        db_row = db_rows[position]
        expected = {
            "id": str(db_row["id"]),
            "event_type": str(db_row["event_type"]),
            "entity_type": str(db_row["entity_type"]),
            "entity_id": db_row["entity_id"],
            "payload": json.loads(str(db_row["payload_json"])),
            "created_at": str(db_row["created_at"]),
        }
        actual = {key: value.get(key) for key in expected}
        if actual != expected:
            raise DataStoreError(
                "Legacy events.jsonl does not exactly match SQLite event order/content; "
                "migration refused.",
                details={
                    "position": position + 1,
                    "db_event_id": expected["id"],
                    "jsonl_event_id": value.get("id"),
                },
            )
        delivered.add(str(db_row["id"]))
    return delivered


def _backfill_legacy_outbox(conn: sqlite3.Connection, delivered_ids: set[str]) -> None:
    now = utc_now_iso()
    rows = conn.execute("SELECT id FROM events ORDER BY sequence").fetchall()
    for row in rows:
        event_id = str(row["id"])
        delivered = event_id in delivered_ids
        conn.execute(
            """
            INSERT INTO outbox_records(
              id, event_id, sink, idempotency_key, status, attempts,
              next_attempt_at, last_error, created_at, updated_at, delivered_at
            )
            VALUES (?, ?, 'jsonl', ?, ?, 0, NULL, NULL, ?, ?, ?)
            """,
            (
                f"OB-LEGACY-{hashlib.sha256(event_id.encode('utf-8')).hexdigest()[:16].upper()}",
                event_id,
                f"jsonl:{event_id}",
                "delivered" if delivered else "pending",
                now,
                now,
                now if delivered else None,
            ),
        )
