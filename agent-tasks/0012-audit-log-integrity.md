# Task 0012: Audit Log Integrity

## Goal

Make `pcl validate --strict` verify that SQLite current state and `.project-loop/events.jsonl` preserve the same append-only event history.

The harness relies on SQLite for queryable state and JSONL for auditability. Strict validation should detect when either side has drifted.

## Scope

Add strict-only validation checks for:

- `.project-loop/events.jsonl` existence;
- JSON Lines parsing and required event fields;
- duplicate event ids in JSONL;
- DB `events` rows missing from JSONL;
- JSONL events missing from DB `events`;
- mismatched `id`, `event_type`, `entity_type`, `entity_id`, `payload`, or `created_at`;
- DB event order differing from JSONL order.

## Acceptance criteria

- Normal `pcl validate` remains backward-compatible.
- `pcl validate --strict --json` returns deterministic error strings for audit log failures.
- Valid init/lifecycle/defect/report flows pass strict validation.
- Tests cover missing JSONL, invalid JSONL, duplicate ids, DB-only events, JSONL-only events, payload mismatch, and order mismatch.
- No schema migration is added.
- Validation never mutates DB or JSONL.

## Do not

- Do not make dashboard rendering depend on strict validation.
- Do not rewrite or repair `events.jsonl` during validation.
- Do not compare raw JSON formatting when semantic payloads are equal.
