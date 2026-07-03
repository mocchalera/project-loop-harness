# Task 0067: Context Pack Improvements

## Goal

Improve read-only context packs so agents can receive focused handoffs for
task backlog work, job leases, role-specific reading priorities, and structured
verification rubric summaries without widening the schema or mutating loop
state.

## Scope

- Add `pcl context pack --task T-0001` alongside `--job`.
- Keep `--job` and `--task` mutually exclusive and require exactly one target.
- Keep the JSON contract version as `context-pack/v1`; this task is an
  additive evolution of the v1 contract.
- Add task-target packs with deterministic sections for machine context rules,
  target task details, dependencies, dependents, linked goal, linked feature or
  defect, sibling tasks, and recent events.
- Include task pack source commands for `pcl task read <id> --json`,
  `pcl task list --json`, and `pcl validate --json`.
- Add lease fields to job target tables: `assigned_agent_id`, `attempts`,
  `lease_expires_at`, and `last_heartbeat_at`.
- Make `--role` select deterministic section priority profiles while rendering
  included sections in canonical document order.
- Add `role_profile` metadata to context pack results and fall back to the
  default profile for unknown or blank roles.
- Add rubric-aware verification columns for `rubric/v1` confidence score and
  evidence completeness.
- Route `work_on_task` next actions to task context packs.
- Update README, architecture/context-pack documentation, and affected tests.

## Acceptance Criteria

- `pcl context pack --task T-0001 --json` returns a `context-pack/v1` package
  with target type `task`.
- Unknown task ids fail with `InvalidInputError` style JSON/error output.
- Task packs show dependency satisfied flags and support no-goal tasks.
- Small `--max-tokens` values truncate deterministically without crashing.
- Repeated packs over the same state produce identical Markdown.
- Job packs render lease fields in the target job section.
- Verifier role packs preserve verification context under tight budgets where
  the default implementer profile omits it.
- Unknown roles fall back to the default role profile.
- Verification rows with `rubric/v1` include confidence score and evidence
  completeness columns; other rows leave those cells blank.
- `pcl next --json` task actions use
  `pcl context pack --task <id> --json`.
- `ruff check .` passes.
- Full `python3 -m pytest` passes.
- Required temp-directory smoke flows pass.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not add or alter tables or columns.
- Do not mutate project-loop state while building context packs.
- Do not append events from context pack commands.
- Do not read or parse generated dashboard HTML.
- Do not write context packs to disk.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, paid services, or plugin distribution.
