# 0140b: Evidence-backed lifecycle integrity gate

- **Status:** Approved v0.4.0 RC2 release blocker
- **Milestone:** v0.4.0 Integrity Gate
- **Priority:** P0
- **Estimated size:** XL
- **Dependencies:** 0140
- **Parallel-safe with:** 0140a, 0140c
- **DB schema:** remains 8

## Problem

Real-task dogfood reproduced a false-completion state that passed strict
validation:

- a `done` Feature still had a `draft` Story;
- a `passing` Test had no Story link and no Workflow Run;
- a `closed` Goal had neither approved Verification nor a target-bound completed
  packet;
- terminal proof was a mutable path string rather than hash-pinned Evidence.

The records existed, but the lifecycle did not prove that the requested
behavior had been reviewed or that the terminal transitions were supported by
healthy artifacts.

## Goal

Reject new false-completion states before mutation while keeping both supported
execution routes valid:

- Workflow-backed work may use its approved Verification and run Evidence.
- Direct work may omit `last_run_id` when it has an approved/waived Story,
  healthy hash-pinned target Evidence, and a target-bound completed packet.

## Scope

### Evidence ID first

- Add mutually exclusive `--evidence-id E-XXXX` support to terminal Test,
  Feature, and Goal commands.
- Validate existence and artifact health before mutation.
- Reuse `test_cases.evidence_id` and generic `evidence_links`; do not add DB
  columns or migrations.
- Add `evidence_id` and `evidence_mode: id|legacy_inline` to event payloads.
- Keep legacy `--evidence` for compatibility and emit a stable warning.

### Mutation guards

- A passing Test requires a same-Feature Story in `approved` or explicit
  `waived` state plus healthy direct Evidence or valid Workflow proof.
- A done Feature requires at least one reviewed Story, passing non-waived
  Tests, no active Defect, and target-bound completion/acceptance Evidence.
- A closed Goal requires an approved Verification from a Goal Workflow Run or a
  same-target `COMPLETED_VERIFIED` / `COMPLETED_WITH_RISK` packet.
- Guard failure changes no domain row, event, outbox row, or JSONL bytes.

### Validation rollout

- New project templates default `validation.lifecycle_integrity` to
  `enforced`.
- Existing projects with no key receive advisory findings for one release.
- Mutation guards apply regardless of advisory/enforced validation severity.

### Direct Goal closure

- Accept a valid `pcl finish --emit-packet --goal G-XXXX` packet Evidence as
  direct Goal closure proof.
- Validate contract, target, artifact health, and outcome.
- Preserve the existing approved Workflow Verification route.

## Invariants

- `last_run_id = null` alone is not an error.
- Story review, waiver, and human Verification are never inferred or
  auto-approved.
- Same-status no-op semantics remain; link repair is a later dedicated command.
- P0 uses schema 8 and standard-library-only code.
- JSON changes are additive; legacy flags are not removed in this release.

## Acceptance criteria

- A synthetic fixture reproduces each dogfood false-completion finding.
- Invalid Test, Feature, and Goal terminal mutations fail with typed errors and
  zero mutation.
- Missing, drifted, cross-target, or wrong-role Evidence is rejected.
- Valid direct and Workflow-backed golden paths both pass.
- Existing inconsistent projects receive advisory findings by default and
  enforced projects receive strict errors.
- Reports and dashboard data identify proof type, Evidence ID, and packet
  outcome without treating HTML as machine state.
- Targeted lifecycle/evidence/validation/finish/report suites pass.
