# 0157: Profile bundle validation and dry-run planner

- **Status:** Done
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P0
- **Size:** L
- **Dependencies:** 0156
- **DB schema:** no change

## Goal

Validate an externally produced bundle and return a deterministic mutation plan
without copying files or touching PLH state.

## Scope

- Add `pcl profile ingest --request ... --bundle ... --dry-run`.
- Enforce parse/size limits before schema validation and reject duplicate keys.
- Validate request/project/target/manifest binding, bundle digest/status,
  listed paths, parents, symlinks, case-fold collisions, files, sizes, hashes,
  contracts, and cross-references.
- Return exact planned Evidence/link/Decision/event counts and next action.
- Add valid status fixtures and a comprehensive invalid corpus.

## Invariants

- Dry-run is entirely read-only and ignores unlisted neighboring files.
- Verification-plan commands are data and are never executed.
- Findings and repair guidance are stable and deterministically ordered.
- `partial`, `budget_exhausted`, and `failed` are never execution-ready.

## Acceptance

1. Valid fixtures yield stable plans and next actions.
2. Every invalid fixture fails with zero filesystem/DB/event mutation.
3. Path traversal, absolute/UNC/drive paths, symlinks, case collisions,
   hash/size drift, bad status, and cross-reference errors are covered.
4. Bundle/request limits are enforced before expensive parsing/hashing.
5. Targeted and full suites pass.

## Implementation evidence

- `src/pcl/profile_ingest.py` validates request/bundle bindings, bounded strict
  JSON, listed artifact bytes, safe paths, contracts, and cross-references.
- `pcl profile ingest --request ... --bundle ... --dry-run` returns a stable,
  exact mutation plan without copying files or executing runner/verification
  commands.
- `tests/fixtures/profile_bundle/cases.json` and
  `tests/test_profile_ingest_dry_run.py` cover all six statuses and the invalid
  corpus, with before/after state snapshots.
- Verification after Claude Fable review fixes: `ruff check .` and `pytest -q`
  (912 passed, 1 skipped).
