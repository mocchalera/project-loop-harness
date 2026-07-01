# Task 0048: Migration Status Command

## Goal

Expose read-only migration status through the CLI so operators can inspect schema state before applying migrations.

The migration runtime already had `migration_status(paths)`, and `pcl doctor` surfaced pending migrations indirectly. Dogfooding F-0001 showed that `pcl migrate` itself needed a non-mutating status mode.

## Scope

Add CLI support for:

- `pcl migrate status`;
- `pcl migrate status --json`.

Behavior:

- Existing `pcl migrate` behavior remains apply-by-default.
- `pcl migrate apply` is accepted as an explicit apply alias.
- Status output includes applied versions, pending migrations, latest supported version, current schema version, and whether `schema_migrations` exists.
- Status does not apply migrations or append events.

## Acceptance criteria

- Fresh initialized projects report no pending migrations.
- Old v1-style databases without `schema_migrations` report `001_initial` as pending.
- Status inspection does not append `migration_applied`.
- Existing `pcl migrate` apply behavior remains idempotent.
- Tests cover fresh and old database status.
- No schema migration is added.

## Do not

- Do not auto-apply migrations from `status`.
- Do not change migration file naming rules.
- Do not add external dependencies.
- Do not make agents edit SQLite directly.
