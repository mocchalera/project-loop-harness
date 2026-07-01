# Task 0052: Lifecycle Failure Job Cleanup

## Goal

Keep workflow failure transitions from leaving active jobs behind.

Dogfooding feature coverage for `F-0006` showed that `pcl loop fail` could mark
a workflow run failed while its queued/running/blocked jobs remained active.
Those jobs could no longer be ingested safely, but they still appeared as stale
queue items.

## Scope

- Make `pcl loop fail WR-0001` cancel active jobs under the failed run.
- Make `pcl jobs fail J-0001` cancel active sibling jobs under the same run.
- Append `agent_job_cancelled` events for jobs cancelled by failure cleanup.
- Include `cancelled_jobs` in JSON responses and `workflow_run_failed` event payloads.
- Keep terminal job/run guards intact.

## Acceptance Criteria

- `pytest tests/test_lifecycle.py tests/test_agents.py tests/test_workflow_executor.py` passes.
- Full `pytest` passes.
- `pcl validate --strict --json` passes.
- No schema migration is added.

## Do Not

- Do not revive terminal jobs.
- Do not mutate SQLite outside lifecycle service functions.
- Do not add dependencies.
- Do not change successful completion semantics.
