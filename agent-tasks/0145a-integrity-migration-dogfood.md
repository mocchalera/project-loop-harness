# 0145a: v0.4.1 integrity migration dogfood

- **Status:** Approved verification slice
- **Milestone:** v0.4.1 Integrity Migration
- **Priority:** P1
- **Estimated size:** M
- **Dependencies:** 0141-0145
- **Parallel-safe with:** no lifecycle or CLI mutation work; this is the serial release gate
- **DB schema:** remains 8

## Problem

Tasks 0141-0145 implement the advisory-to-enforced migration path, but the
v0.4.1 roadmap requires a complete dogfood run before existing projects are
changed from advisory to enforced lifecycle validation. Unit fixtures alone do
not prove that a real project created by an older released CLI can be upgraded,
planned, repaired, and validated through public operator commands.

## Goal

Exercise the full migration against an isolated project created with the
released v0.3.0 CLI, record a reproducible transcript, and add a regression
gate for the supported migration sequence. The run must not fabricate Story
approval, Evidence, Verification, or terminal status changes.

## Required migration sequence

1. Create an isolated legacy project with the v0.3.0 source and public `pcl`
   commands. Produce a lifecycle relationship gap that v0.3.0 accepted.
2. Upgrade the project with current `PYTHONPATH=src python -m pcl migrate`.
3. Run the read-only lifecycle plan twice. Prove deterministic output and zero
   project-state mutation.
4. Apply only `repair lifecycle --apply-structural` actions.
5. Resolve every remaining semantic or human-review action with an explicit,
   named public command. Approval commands must include a human-authored
   summary; repair code must never choose or approve on the operator's behalf.
6. Enable `validation.lifecycle_integrity: enforced` only after repair.
7. Run strict validation, render, and the relevant test suite.

## Scope

- Add a focused end-to-end regression test for the supported migration path.
- Add `docs/dogfood-report-v0.4.1-integrity-migration.md` with versions,
  commands, before/after findings, event evidence, determinism hashes, and
  residual risks.
- Correct only defects directly exposed by this dogfood run. Any behavioral
  correction requires a regression test and must preserve schema 8, existing
  JSON contracts, and advisory defaults for legacy projects.
- Update the v0.4.1 plan status only after every gate passes.

## Invariants

- No direct SQLite write is part of the operator migration transcript.
- No generated dashboard HTML is read or edited as state.
- Planner runs are wholly read-only; structural apply never executes emitted
  command strings.
- Semantic choices remain explicit. Candidate count never implies approval.
- Existing-project policy remains advisory until its operator changes config.
- Fresh-project defaults, dependency set, completion packet, and schema 8 stay
  unchanged.
- No push, tag, package upload, or other release publication is part of this
  task.

## Acceptance criteria

- A project created by v0.3.0 migrates to schema 8 with current code.
- Two repair plans for identical state are byte-identical and all emitted
  read-only inspection commands execute successfully through the real CLI.
- Planner mode changes no tracked state hash or event count.
- Structural apply changes only the relationships advertised as safe and is an
  event-free no-op on exact rerun.
- Remaining semantic/human actions are cleared only by explicit Story,
  Evidence, Test, or Verification commands named in the transcript.
- Enforced strict validation ends with zero errors and zero lifecycle findings.
- Targeted tests, full `pytest`, `ruff check .`, validation, and render pass.
- The report is sufficient for an independent reviewer to reproduce the run.

## Evidence required to close

- Legacy and current revision/version identifiers.
- Pre/post schema and policy values.
- Repair-plan SHA-256 values and state/event counts around both planner runs.
- Structural repair event and idempotent rerun output.
- Explicit semantic command transcript and final strict JSON summary.
- Independent read-only review of the report and regression coverage.
