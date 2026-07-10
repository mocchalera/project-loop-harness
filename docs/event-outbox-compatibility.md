# Event outbox compatibility and recovery

Schema version 8 makes SQLite the authoritative commit point for domain state,
ordered events, and JSONL projection intent. `events.jsonl` may temporarily lag
SQLite. A mutation that reports `audit_projection_pending` has already committed:
do not repeat it; run `pcl audit flush --json`.

## Upgrade behavior

- Migration 008 reads and validates legacy JSONL before opening its schema
  transaction. Exact legacy prefixes are mapped to delivered outbox rows without
  rewriting their bytes.
- A missing JSONL file or a DB-only suffix is recoverable and becomes pending.
- Duplicate IDs, malformed/partial lines, field mismatch, order mismatch,
  JSONL-only events, and interior gaps refuse migration without changing schema.
- Migration SQL, sequence backfill, outbox backfill, migration metadata, and
  migration events commit atomically under the exclusive project-operation lock.

The installed package includes `db/migrations/008_event_outbox.sql` through the
existing `db/migrations/*.sql` package-data rule.

## Downgrade and rollback

An older binary cannot create a valid event on schema 8 because it does not
provide the required `events.sequence`; mutation with the older binary is not
supported. Read-only SQLite inspection remains possible for queries that do not
assume the old events column list.

Before upgrading a real project, stop concurrent writers and back up the complete
SQLite set (`project.db` plus `-wal`/`-shm` when present) and `events.jsonl`. If no
schema-8 mutation has committed, rollback means restoring that complete backup
set. After a schema-8 event commits, do not reverse-migrate or restore files
individually. Preserve the artifacts, leave pending outbox rows intact, and roll
forward with the schema-8 binary.

Projector errors do not authorize deleting committed events or domain rows.
Content mismatches, malformed tails, and unknown lines enter
`failed_needs_review`; automatic truncation, overwrite, and skip are intentionally
not implemented.

## Integrity commands

`pcl audit check --json` is read-only and does not flush pending projection.
It reports audit and Evidence anomalies as repairable, human-review, or
unsupported. `pcl audit repair` is preview-only unless `--apply` is explicit;
the supported automatic repair is a pending/retryable SQLite suffix that the
existing projector can deliver idempotently.

`pcl audit rebuild-jsonl --from-sqlite` writes a canonical verified preview.
With `--apply`, it retains the original JSONL and its hash in
`.project-loop/reports/audit-backups/`, then uses atomic replace. Unknown and
legacy lines remain available in that backup and are listed in the result.
Neither repair command imports JSONL-only history into SQLite or claims to fix
arbitrary SQLite corruption.
