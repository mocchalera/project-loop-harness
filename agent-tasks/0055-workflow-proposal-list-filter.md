# Task 0055: Workflow Proposal List Filter

## Goal

Make workflow proposal review queues easier to inspect during dogfooding by filtering proposal lists by derived review status.

## Scope

- Add `pcl workflow proposals list --status proposed|approved|cancelled|unknown`.
- Filter using the same event-derived status already returned by proposal read/list records.
- Keep `pcl workflow proposals list` without a filter backward compatible.
- Reject invalid status values before state changes.
- Add regression coverage for mixed proposed, approved, and cancelled proposal queues.

## Acceptance Criteria

- JSON output remains deterministic.
- Unfiltered list output still returns all proposal records in proposal id order.
- Filtered list output returns only proposals whose derived `status` matches the requested status.
- Invalid status values are rejected by CLI argument validation.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not change workflow proposal event names or payloads.
- Do not execute workflow proposals.
- Do not add automatic approval or cancellation.
- Do not make dashboard rendering depend on strict validation.
