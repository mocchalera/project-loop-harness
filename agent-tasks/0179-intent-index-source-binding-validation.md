# 0179: Intent-index source-binding validation

- **Status:** Complete
- **Milestone:** v0.5.1 Trace & Efficient Handoff
- **Priority:** P0
- **Size:** M
- **Dependency:** 0178 contract and fixture freeze
- **DB schema:** remains 8

## Goal

Make existing read-only contract and context preflight surfaces determine
whether an `intent-index/v0` artifact is structurally valid and bound to the
recorded copied `master-trace/v0` bytes and addressable line ranges.

## Scope

1. Add a standard-library parser/validator for the frozen trace/index fixtures.
2. Validate `source_trace` against the linked Evidence manifest, copied stored
   path, and recorded/actual SHA-256.
3. Validate unique item IDs and non-empty source refs with positive,
   one-based-inclusive ranges inside the copied trace.
4. Extend `pcl context check --task ... --json` with factual binding status and
   stable typed diagnostics.
5. Add structural file validation through the existing contract-validation
   family when it can remain project-state independent.
6. Keep all validation and preflight paths mutation-free.

## Invariants

- Validation does not claim that index wording is correct, complete, relevant,
  approved, or safe to execute.
- A structural-only contract check does not claim Evidence binding.
- No new state-changing command, database table, dependency, or LLM call.
- Ambiguous multiple trace/index candidates remain explicit and fail closed.

## Acceptance

1. Every invalid 0178 fixture returns its expected stable diagnostic.
2. Binding failure is reported before claim selection or a resume recommendation.
3. Valid binding identifies the exact copied trace/index Evidence and hashes.
4. `pcl context check` remains read-only under success and every failure mode.
5. No-index and pre-v0.5.1 compatibility fixtures remain unchanged.
6. Targeted tests, full lint/test, strict validation, and render pass.

## Non-goals

- Semantic claim verification.
- Claim ranking or handoff rendering.
- Provider execution, telemetry, or migration.

## Completion evidence

- `docs/evidence/0179-intent-index-source-binding-validation.md`
