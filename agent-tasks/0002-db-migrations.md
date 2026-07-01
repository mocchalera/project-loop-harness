# Task 0002: Implement DB Migrations

## Goal

Replace single-shot schema initialization with versioned migrations.

## Read first

- `src/pcl/db/schema.sql`
- `src/pcl/db/migrations/001_initial.sql`
- `docs/data-model.md`
- `docs/adr/0001-hybrid-state.md`

## Scope

Implement:

- migration discovery;
- `schema_migrations` table;
- `pcl migrate` command;
- `pcl doctor` warning when migrations are pending;
- rollback-free forward migrations for now;
- tests using temporary SQLite DBs.

## Acceptance criteria

- New project initializes at latest schema.
- Old DB with no migrations table can be upgraded safely.
- Re-running migrate is idempotent.
- Migrations append a system event.

## Do not

- Do not commit local `.project-loop/project.db` files.
- Do not allow agents to write arbitrary migration SQL without human review.
