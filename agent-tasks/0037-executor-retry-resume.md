# Task 0037: Executor Retry And Resume

## Goal

Make the guarded workflow executor recoverable after interrupted or failed
workflow execution.

Tasks 0035 and 0036 made automatic execution possible and dogfoodable. The next
step is to make recovery explicit, event-backed, and visible through
`pcl next`.

## Scope

Add guarded executor recovery support:

- `pcl loop execute workflow_id --retry WR-0001`;
- `pcl loop execute workflow_id --resume WR-0001`;
- retry creates a new workflow run linked to the failed or cancelled source run;
- resume executes against an existing active workflow run without creating a new
  run;
- retry/resume relationships are recorded in events and executor evidence;
- `pcl next --json` routes unfinished executor runs to `resume_workflow_execution`;
- `pcl next --json` routes unretried failed executor runs to
  `retry_workflow_execution`.

## Acceptance criteria

- `--retry` only accepts failed or cancelled workflow runs for the same
  workflow id.
- `--retry` rejects a source workflow run that already has a linked retry run.
- `--retry` creates a new workflow run and records the source run id in event
  payloads and execution evidence.
- retry run creation and retry-link event recording happen in one transaction.
- retry increments the new run iteration from the source run.
- `--resume` only accepts active workflow runs for the same workflow id.
- `--resume` does not create a new workflow run.
- invalid retry/resume transitions return typed JSON errors.
- `pcl next --json` suggests resume for active executor runs whose latest
  executor event has no matching finish event.
- `pcl next --json` suggests retry for failed executor runs that have not
  already been retried.
- Tests cover retry success, resume success, invalid retry, and next-action
  routing.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not auto-retry failed workflow runs.
- Do not skip sandbox verification on retry or resume.
- Do not resume terminal workflow runs.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service
  functions.
- Do not add hosted services or external queues.
