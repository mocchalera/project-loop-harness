# Task 0064: Task Loop Integration

## Goal

Integrate the first-class task backlog into the local project loop so agents can
route, review, export, and report goal-linked task work without adding new state
mutations or widening the schema.

## Scope

- Add read-only `pcl next` routing for goal-linked tasks at priority 59.
- Route in-progress tasks before starting new ready or todo tasks.
- Route actionable todo/ready tasks only when every dependency is done,
  cancelled, or waived.
- Consider only tasks whose `related_goal_id` points to an `open` or `active`
  goal.
- Keep unlinked tasks out of `pcl next` routing in v1.
- Add deterministic task rows to `dashboard-data.json`.
- Add a human-readable Task Backlog table to generated dashboard HTML.
- Add `tasks.csv` and `task_dependencies.csv` to complete CSV export.
- Add an optional Tasks section to goal reports when a goal has tasks.
- Update tests, README, and dashboard data contract documentation.

## Acceptance Criteria

- A goal-linked ready task with satisfied dependencies returns `work_on_task`
  from `pcl next --json` with priority 59.
- Checkpoint review at priority 58 still wins over task routing.
- Open goal continuation at priority 60 is reached when no routable task exists.
- In-progress goal-linked tasks are preferred over ready tasks.
- Dependency-blocked tasks are skipped until dependencies reach done,
  cancelled, or waived.
- Tasks without `related_goal_id` are ignored by `pcl next` in v1.
- `dashboard-data.json` contains a deterministic `tasks` section.
- Generated dashboard HTML contains a Task Backlog table.
- Complete CSV export includes `tasks.csv` and `task_dependencies.csv`.
- `pcl report goal` includes a Tasks section with unmet dependency counts when
  tasks exist and omits it when none exist.
- `ruff check .` passes.
- Full `pytest` passes.
- `/tmp/pcl-demo-nexttask` smoke flow proves dependency-aware task routing.

## Do Not

- Do not add a schema migration.
- Do not change `src/pcl/tasks.py` service functions.
- Do not add dependencies.
- Do not change existing `pcl next` priorities, types, or fields.
- Do not make agents write SQLite directly.
- Do not make agents parse or edit generated dashboard HTML as state.
