# Task 0045: Filtered Job Inspection

## Goal

Make `pcl jobs list` useful in long-lived dogfooded projects by allowing agents and humans to inspect jobs for one workflow run or one status without dumping all historical jobs.

## Scope

Add CLI/runtime support for:

- `pcl jobs list --run WR-0001`;
- `pcl jobs list --status queued`;
- `pcl jobs list --run WR-0001 --status queued`.

Behavior:

- JSON output keeps the existing `{"ok": true, "jobs": [...]}` shape.
- Text output keeps the existing one-line job format.
- Unknown workflow run IDs return a typed `invalid_input` error.
- Invalid status values are rejected by CLI choices or service validation.
- Job evidence enrichment still works for filtered results.

## Acceptance criteria

- Filtering by `--run` returns only jobs for that workflow run.
- Filtering by `--status` returns only jobs with that status.
- Combining both filters applies both predicates.
- Unknown `--run` returns a typed JSON error.
- Existing unfiltered behavior remains unchanged.
- Tests cover run filtering, status filtering, combined filtering, and unknown-run errors.
- No schema migration is added.

## Do not

- Do not change job lifecycle states.
- Do not make agents query SQLite directly.
- Do not add external dependencies.
- Do not make dashboard rendering depend on these filters.
