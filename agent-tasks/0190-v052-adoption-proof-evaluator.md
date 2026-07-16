# 0190: v0.5.2 Adoption Proof evaluator and participant kit

- **Status:** Done; implemented and verified
- **Milestone:** v0.5.2 Adoption Proof
- **Priority:** P0
- **Size:** S
- **Dependency:** 0189 config-ready adoption and frozen cohort thresholds
- **DB schema:** remains 8

## Goal

Make the external first-use cohort executable and non-negotiably evaluable by
providing one participant kit, one privacy-safe record contract, and one
deterministic threshold evaluator.

## Scope

1. Freeze `adoption-observation/v1` as an exact sanitized JSON record.
2. Bind every participant record to the same candidate ID and SHA-256.
3. Evaluate the predeclared cohort gates without network access or dependencies.
4. Return exit 0 only when every gate passes, exit 1 for valid incomplete or
   failed evidence, and exit 2 for invalid evidence.
5. Give participants and observers a bounded, non-leading session guide.

## Invariants

- No names, repository URLs, source code, credentials, full transcripts, or
  telemetry in the evaluator record.
- No post-hoc threshold changes, participant exclusion, or candidate mixing.
- No external recruitment, artifact transfer, publication, or provider call.
- Internal demo and download metrics never satisfy an external cohort gate.

## Acceptance

1. Passing, incomplete, failed, malformed, duplicate, and inconsistent fixtures
   produce deterministic status, reasons, and exit codes.
2. All five records must bind the same candidate artifact.
3. `ready_to_claim` is the conjunction of every frozen gate.
4. Participant kit and protocol name the same fields, timing, and intervention
   boundary.
5. Ruff, targeted tests, full pytest, strict PCL validation, render, and diff
   check pass.

## Completion evidence

- `docs/evidence/0190-v052-adoption-proof-evaluator.md`
