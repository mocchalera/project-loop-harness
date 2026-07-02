# Task 0063: Structured Verification Rubric v1

## Goal

Add an opt-in structured verification rubric contract so verification records
can carry machine-readable acceptance, risk, evidence, and confidence metadata
without changing the database schema or breaking existing free-form rubrics.

## Scope

- Add a `rubric/v1` JSON contract validator.
- Keep validation opt-in via `contract_version: "rubric/v1"`.
- Add `--rubric-file` to `pcl verification record`.
- Reject invalid `rubric/v1` payloads before recording.
- Reject missing referenced evidence ids before recording.
- Include `rubric_contract_version` in `verification_recorded` event payloads.
- Add read-only `pcl verification list` and `pcl verification read` commands.
- Add normal/strict validation diagnostics for stored structured rubrics.
- Add compact `rubric/v1` summaries to run reports.
- Document the contract and command boundaries.

## Acceptance Criteria

- Existing free-form `--rubric-json '{}'` verification recording still works.
- `pcl verification record --rubric-json ...` accepts valid `rubric/v1`.
- `pcl verification record --rubric-file rubric.json` accepts valid `rubric/v1`.
- Invalid `rubric/v1` payloads fail with human-readable problem strings and
  append no event.
- Missing `evidence_id` references fail before recording.
- `pcl verification list --json` returns records ordered by `created_at, id`.
- `pcl verification read V-0001 --json` includes a parsed rubric object.
- `pcl validate` warns on invalid stored `rubric/v1`; strict mode errors.
- `pcl validate --strict` errors on missing rubric evidence references.
- `pcl report run WR-0001` includes compact rubric counts for `rubric/v1`.
- `ruff check .` passes.
- Full `pytest` passes.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not add or alter tables.
- Do not change dashboard or renderer behavior.
- Do not change `pcl next` routing.
- Do not add MCP or plugin distribution changes.
- Do not make agents write SQLite directly.
