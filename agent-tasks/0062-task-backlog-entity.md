# Task 0062: Task Backlog Entity v1

## Goal

Add a first-class task/backlog entity so local agent loops can track actionable
work items, ownership hints, risk, priority, and dependency order without using
dashboard HTML or ad hoc notes as state.

## Scope

- Add schema migration `002_tasks.sql`.
- Add `tasks` and `task_dependencies` tables with forward-only migrations.
- Add task service functions for create, list, read, status changes, dependency
  add, and dependency removal.
- Add `pcl task create/list/read/status/depend/undepend`.
- Record every mutation through `append_event`.
- Reject self dependencies, duplicates, unknown task ids, and dependency cycles.
- Validate task foreign-key references, dependency cycles, and done tasks with
  incomplete dependencies.
- Cover task behavior with CLI/service tests and migration upgrade tests.

## Acceptance Criteria

- `pcl task create --title "Sample task" --json` returns `T-0001`.
- `pcl task list --json` is ordered by priority then id.
- `pcl task read T-0001 --json` includes dependencies and dependents.
- `pcl task status T-0001 ready --reason "..." --json` records a status event.
- `pcl task depend T-0002 --on T-0001 --json` records a dependency event.
- Direct and transitive dependency cycles are rejected.
- Existing schema-1 databases migrate cleanly to schema 2.
- `ruff check .` passes.
- Full `pytest` passes.
- `/tmp/pcl-demo-tasks` init/create/list/validate/render smoke flow passes.

## Do Not

- Do not route tasks through `pcl next` in this task.
- Do not edit renderer, dashboard, reports, MCP server, or context packs.
- Do not add dependencies.
- Do not make agents write SQLite directly.
