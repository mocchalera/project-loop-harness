from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from importlib import resources

from .db import connect, get_metadata, table_exists
from .errors import DataStoreError, ProjectNotInitializedError
from .events import append_event
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

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "applied": [migration.to_dict() for migration in self.applied],
            "pending_before": [migration.to_dict() for migration in self.pending_before],
            "latest_version": self.latest_version,
        }


@dataclass(frozen=True)
class MigrationStatus:
    applied_versions: list[int]
    pending: list[Migration]
    latest_version: int
    current_schema_version: int | None
    has_migrations_table: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "applied_versions": self.applied_versions,
            "pending": [migration.to_dict() for migration in self.pending],
            "latest_version": self.latest_version,
            "current_schema_version": self.current_schema_version,
            "has_migrations_table": self.has_migrations_table,
        }


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


def migration_status(paths: ProjectPaths) -> MigrationStatus:
    migrations = discover_migrations()
    latest = max((migration.version for migration in migrations), default=0)
    conn = connect(paths.db_path)
    try:
        has_table = table_exists(conn, "schema_migrations")
        applied_versions = _applied_versions(conn)
        applied_set = set(applied_versions)
        pending = [migration for migration in migrations if migration.version not in applied_set]
        return MigrationStatus(
            applied_versions=applied_versions,
            pending=pending,
            latest_version=latest,
            current_schema_version=_schema_version(conn),
            has_migrations_table=has_table,
        )
    finally:
        conn.close()


def apply_migrations(paths: ProjectPaths) -> MigrationResult:
    if not paths.loop_dir.exists() or not paths.db_path.exists():
        raise ProjectNotInitializedError(root=str(paths.root))

    migrations = discover_migrations()
    latest = max((migration.version for migration in migrations), default=0)
    conn = connect(paths.db_path)
    try:
        ensure_schema_migrations_table(conn)
        applied_versions = set(_applied_versions(conn))
        pending = [migration for migration in migrations if migration.version not in applied_versions]
        applied: list[Migration] = []
        for migration in pending:
            conn.executescript(migration.sql)
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
                    ("pcl_version", "0.1.0"),
                )
            if table_exists(conn, "events"):
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
            conn.commit()
            applied.append(migration)
        if latest and table_exists(conn, "metadata"):
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(latest)),
            )
            conn.commit()
        return MigrationResult(applied=applied, pending_before=pending, latest_version=latest)
    finally:
        conn.close()
