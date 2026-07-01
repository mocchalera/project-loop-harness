# Task 0009: Defect Lifecycle

## Goal

Close the remaining core-loop gap by adding guarded defect lifecycle transitions.

The schema already models defects as `open -> triaged -> in_progress -> fixed -> verified -> closed/waived`, but the CLI currently only supports `defect open`.

## Scope

Add CLI/runtime commands for:

- `pcl defect triage D-0001 --summary "..."`;
- `pcl defect start D-0001 --summary "..."`;
- `pcl defect fix D-0001 --summary "..." --evidence "..."`;
- `pcl defect verify D-0001 --summary "..." --verification V-0001`;
- `pcl defect close D-0001 --summary "..." --evidence "..."`;
- `pcl defect waive D-0001 --reason "..."`.

Improve `pcl next` so open defects point to the appropriate next defect command instead of always suggesting a new repair workflow.

## Acceptance criteria

- Every defect lifecycle mutation appends an event.
- Invalid transitions fail with typed JSON errors.
- Fixing a defect requires explicit evidence.
- Verifying a defect requires an approved verification from a workflow run tied to that defect.
- Closing a defect requires verified status and explicit evidence.
- Waiving a defect requires an explicit reason.
- Closing or waiving the last active defect updates the related feature status out of `needs_fix`.
- Dashboard counts treat `closed` and `waived` defects as not open.

## Do not

- Do not add a schema migration unless the existing defect columns are insufficient.
- Do not bypass `pcl` for state changes.
- Do not auto-run external agents.
- Do not add hosted sync or arbitrary shell execution.
