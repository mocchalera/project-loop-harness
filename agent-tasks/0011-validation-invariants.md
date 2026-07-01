# Task 0011: Validation Invariants

## Goal

Make `pcl validate --strict` catch broken loop state that can no longer be trusted as evidence-backed progress.

The harness already guards normal transitions, but strict validation should also detect corrupted or legacy state where terminal statuses are missing the proof required by the control loop.

## Scope

Add strict-only validation checks for:

- closed goals must have closure evidence or an approved verification;
- passed workflow runs must have all jobs passed and an approved verification;
- verified or closed defects must have fix/close evidence and an approved verification tied to the defect;
- active workflow runs must not duplicate the same goal or defect target.

## Acceptance criteria

- `pcl validate` remains backward-compatible and does not fail on strict-only invariants.
- `pcl validate --strict --json` returns deterministic error strings for invariant failures.
- Strict validation still treats normal warnings as errors.
- Tests cover each invariant with intentionally inconsistent temp project state.
- Valid closed goal/run/defect lifecycle examples pass strict validation.

## Do not

- Do not add a schema migration.
- Do not mutate state during validation.
- Do not hide failures as warnings in strict mode.
- Do not make dashboard rendering depend on strict validation.
