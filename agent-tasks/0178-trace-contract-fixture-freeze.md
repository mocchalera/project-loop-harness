# 0178: Trace contract and fixture freeze

- **Status:** Complete
- **Milestone:** v0.5.1 Trace & Efficient Handoff
- **Priority:** P0
- **Size:** S-M
- **Dependency:** 0177 advisory checkpoint routing
- **DB schema:** remains 8

## Goal

Freeze the smallest additive contract needed to validate and consume
claim-bound `intent-index/v0` handoffs without inventing a first-class Trace
entity or changing existing no-index behavior.

## Scope

1. Characterize the current `master_trace_context` and `pcl resume` behavior
   with baseline fixtures before changing it.
2. Freeze valid and invalid trace/index pairs covering Evidence ID, manifest
   path, copied stored path, SHA-256, item identity, and line ranges.
3. Define an optional additive handoff field for bounded unverified claim refs,
   deterministic ordering, and omission reasons.
4. Define the controlled evaluation case/result format used by 0181.
5. Update contract docs to distinguish structural/source binding from semantic
   correctness.

## Invariants

- No runtime behavior, state mutation, schema migration, dependency, or LLM
  call is introduced in this task.
- Full trace text and referenced source-line text are not packet fields.
- A claim ref never enters the existing `verified` array.
- Existing v1 packets without the new optional field remain valid.

## Acceptance

1. Current behavior is pinned by characterization tests.
2. Fixtures include valid binding plus hash mismatch, Evidence mismatch, path
   mismatch, unsupported contract, duplicate item ID, empty refs, reversed
   range, and out-of-bounds range.
3. Contract examples are internally consistent and deterministic.
4. The 0181 evaluation schema freezes success, assistance, safe-stop, byte-size,
   and trust-boundary fields before dogfood begins.
5. Targeted contract/fixture tests and `git diff --check` pass.

## Non-goals

- Validator implementation.
- Context/resume claim selection.
- Real provider execution or external-user recruitment.
- Release preparation.

## Completion evidence

- `docs/evidence/0178-trace-contract-fixture-freeze.md`
