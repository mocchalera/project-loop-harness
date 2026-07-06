from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from importlib import resources

from . import __version__ as PCL_VERSION
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
    metadata_repair: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "applied": [migration.to_dict() for migration in self.applied],
            "pending_before": [migration.to_dict() for migration in self.pending_before],
            "latest_version": self.latest_version,
            "metadata_repaired": self.metadata_repair is not None,
            "metadata_repair": self.metadata_repair,
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
    conn = connect(paths.db_path)
    try:
        ensure_schema_migrations_table(conn)
        status = _migration_status_for_conn(conn=conn, paths=paths, migrations=migrations)
        if status.is_ahead_of_binary:
            raise SchemaVersionAheadError(status=status)
        pending = status.pending
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
                    ("pcl_version", PCL_VERSION),
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
                    "metadata.schema_version was behind schema_migrations; "
                    "no DDL was run"
                ),
                "schema_migration_applied": False,
            }
            if table_exists(conn, "events"):
                append_event(
                    conn=conn,
                    events_path=paths.events_path,
                    event_type="schema_metadata_repaired",
                    entity_type="system",
                    entity_id="metadata:schema_version",
                    payload=repair,
                )
            conn.commit()
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
        return MigrationResult(
            applied=applied,
            pending_before=pending,
            latest_version=latest,
            metadata_repair=repair,
        )
    finally:
        conn.close()
