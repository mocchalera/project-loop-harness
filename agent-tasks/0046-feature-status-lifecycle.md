# Task 0046: Feature Status Lifecycle

## Goal

Add a guarded CLI command for evidence-backed feature status changes.

Dogfooding showed that older discovered features can remain stuck even after implementation or external verification, because `pcl feature` only supports `add`, `list`, and `read`. Operators should not need direct SQLite edits or artificial story/test records to reconcile feature coverage state.

## Scope

Add CLI/runtime support for:

- `pcl feature status F-0001 --status passing --summary "..." --evidence "..."`.

Behavior:

- Validate feature ID and target status.
- Require non-empty summary and evidence.
- Reject no-op status changes.
- Update `features.status` and `updated_at`.
- Record inline evidence with type `feature_status`.
- Append a `feature_status_updated` event with previous status, target status, summary, evidence, evidence ID, and source.
- Return predictable JSON.

## Acceptance criteria

- Successful status change updates `pcl feature read`.
- Successful status change creates evidence and appends an event.
- Missing evidence returns a typed JSON error.
- No-op status changes return a typed JSON error.
- Invalid target status returns a typed JSON error.
- Existing feature list/read behavior remains unchanged.
- Tests cover success and invalid transitions.
- No schema migration is added.

## Do not

- Do not make agents edit `.project-loop/project.db` directly.
- Do not infer status automatically from free text.
- Do not add external dependencies.
- Do not change automatic story/test/defect feature status refresh behavior.
