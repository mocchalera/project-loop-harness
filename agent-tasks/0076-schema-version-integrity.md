# Task 0076: Schema Version Integrity and Downgrade Guard

## Goal

Make schema version reporting trustworthy and make it impossible for an
older pcl binary to silently downgrade `metadata.schema_version` on a
newer database. Found by dogfooding on 2026-07-05: this repo's live
`.project-loop/project.db` has `schema_migrations` rows 1-4 but
`metadata.schema_version = 3`, `pcl validate --strict` fails with
"Schema version 3 is behind latest 4", while `pcl migrate status --json`
reports `applied_versions: [1,2,3,4]`, `pending: []`,
`current_schema_version: 3` with no warning about the contradiction.

## Root cause (confirmed)

`apply_migrations` in `src/pcl/migrations.py` ends with an unconditional
stamp: `if latest and table_exists(conn, "metadata")` it sets
`metadata.schema_version = str(latest)`, where `latest` is the highest
migration version THE RUNNING BINARY ships. If an older binary (e.g.
pipx-installed 0.1.8, which ships migrations 1-3 only) runs
`pcl migrate` against a database already migrated to 4, `pending` is
empty but the final stamp still executes and DOWNGRADES metadata from 4
to 3. The event log confirms migration 004 was applied normally on
2026-07-05T00:01:42; a later old-binary run rewound the metadata.

## Scope

- `apply_migrations`: never stamp a lower version. The final stamp must
  set `max(latest, current_metadata_version, max(applied_versions))`
  semantics — concretely: if the DB's applied versions or current
  metadata exceed the binary's `latest`, do not lower metadata; instead
  report that the database is ahead of the running binary.
- When the DB contains applied migration versions unknown to the running
  binary (DB ahead of binary), `pcl migrate` must refuse to apply
  anything, exit with a typed command error naming both versions, and
  advise upgrading pcl. Read-only commands keep working.
- `migration_status` / `pcl migrate status --json` must surface
  inconsistencies explicitly. Add fields (additive):
  - `metadata_schema_version` (what metadata says),
  - `max_applied_version` (from schema_migrations),
  - `consistent: bool`,
  - `warnings: [...]` describing any mismatch (metadata behind applied,
    metadata ahead of applied, DB ahead of binary).
  Keep the existing fields so current consumers do not break.
- Reconciliation path: when `pending` is empty but metadata is BEHIND
  `max_applied_version` (this repo's exact state), `pcl migrate` repairs
  metadata upward to `max_applied_version`, prints exactly what it
  repaired and why, appends a `schema_metadata_repaired` event, and
  applies no DDL. This is a metadata repair, not a schema migration; the
  output must say so.
- `pcl validate` (strict and non-strict) and `pcl migrate status` must
  agree: validate's schema-version messages should be derived from the
  same consistency computation, and when the state is repairable,
  validate's advice must name the exact command that will repair it.
- Document the failure mode and the repair in
  `docs/recovery-playbook.md`.

## Acceptance Criteria

- Regression test reproducing the dogfood state: build a DB with
  schema_migrations rows 1-4 and metadata.schema_version=3; assert
  `migrate status` reports `consistent: false` with a metadata-behind
  warning, `validate --strict` fails with advice naming the repair
  command, running `pcl migrate` repairs metadata to 4 with a
  `schema_metadata_repaired` event and no DDL, and afterwards both
  `validate --strict` and `migrate status` are clean and consistent.
- Downgrade guard test: simulate an older binary by monkeypatching
  discovered migrations to versions 1-3 against a DB at 4; assert
  `pcl migrate` refuses with a typed error, applies nothing, and leaves
  metadata at 4.
- Consistent-state test: a freshly initialized project reports
  `consistent: true` and no new warnings.
- `ruff check .` passes; full `python3 -m pytest` passes (337 currently
  green); `pcl init` smoke against a temp dir passes.
- No new migration file, no dependency, no contract version bump
  (migrate-status JSON evolves additively).

## Do Not

- Do not add a new schema migration for this.
- Do not auto-run repairs from read-only commands (`status`, `validate`
  only diagnose and advise; `migrate` repairs).
- Do not touch this repository's live `.project-loop/project.db` as part
  of the task — tests use fixtures only. Repairing the live DB is a
  separate human-approved operation.
- Do not use raw SQL against live project state outside the migration
  runner's own connection handling.
- Do not add hosted services, telemetry, or new runtime dependencies.
