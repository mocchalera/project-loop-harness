# Task 0008: Loop Lifecycle

## Goal

Make project-loop dogfooding finishable by adding guarded lifecycle transitions for queued agent jobs, workflow runs, verifications, and goals.

The current harness can create goals, workflow runs, and jobs, but it cannot close the loop cleanly. This task should make `pcl next` stop recommending duplicate workflow runs when an active run already exists.

## Scope

Add CLI/runtime commands for:

- marking an agent job complete, failed, or cancelled;
- recording a verification result for a workflow run;
- marking a workflow run complete, failed, or cancelled;
- closing or cancelling a goal;
- improving `pcl next` so active workflow runs and queued jobs are handled before new runs are suggested.

## Acceptance criteria

- Every lifecycle mutation appends an event.
- Invalid transitions fail with typed JSON errors.
- Completing a workflow run requires all jobs to pass and an approved verification.
- Closing a goal requires explicit evidence text or an approved verification.
- Cancelling a workflow run cancels non-terminal jobs in that run.
- `pcl next` does not suggest creating another workflow run while a queued/running/blocked run already exists.
- Dashboard rendering still derives from SQLite state and remains deterministic.

## Suggested commands

```bash
pcl jobs complete J-0001 --summary "Mapped the surfaces"
pcl jobs fail J-0001 --summary "Prompt could not be completed"
pcl jobs cancel J-0001 --summary "Superseded by another run"

pcl verification record --run WR-0001 --result approved --reason "pytest passed"

pcl loop complete WR-0001 --summary "Feature coverage complete"
pcl loop fail WR-0001 --summary "Verifier rejected output"
pcl loop cancel WR-0001 --summary "Superseded by newer run"

pcl goal close G-0001 --summary "Task implemented" --evidence "commit abc123, pytest passed"
pcl goal cancel G-0001 --summary "No longer needed"
```

## Do not

- Do not add a schema migration unless the existing lifecycle columns are insufficient.
- Do not let agents write SQLite directly.
- Do not auto-run external agents.
- Do not add hosted sync or arbitrary shell execution.
