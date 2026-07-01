# Task 0041: Feature Inspection Commands

## Goal

Add read-only CLI commands for inspecting tracked features.

Story and test coverage now depends on feature identifiers, but `pcl feature` only exposes `add`. Operators should not need to switch to dashboard output, CSV export, MCP, or direct database inspection to find the feature ID and status they need for stories, tests, defects, or reports.

## Scope

Add CLI/runtime support for:

- `pcl feature list [--status discovered|specified|needs_test|needs_fix|passing|done|waived]`;
- `pcl feature read F-0001`.

## Acceptance criteria

- `pcl feature list --json` returns deterministic feature rows ordered by feature ID.
- `pcl feature list --status passing --json` filters by feature status.
- `pcl feature read F-0001 --json` returns one feature row.
- Missing feature IDs and invalid statuses return typed JSON errors.
- Existing `pcl feature add` behavior remains unchanged.
- Tests cover list, read, status filtering, and errors.
- No schema migration is added.

## Do not

- Do not add feature mutation commands in this task.
- Do not write SQLite directly outside existing service functions.
- Do not make dashboard rendering depend on these read commands.
