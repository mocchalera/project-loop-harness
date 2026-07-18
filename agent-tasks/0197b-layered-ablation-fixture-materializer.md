# 0197b: Layered Ablation Fixture Materializer

- **Status:** Complete
- **Milestone:** Harness Minimization Phase 4
- **Priority:** P0
- **Size:** M
- **Dependency:** 0197 frozen cohort and T-0116 offline evaluator
- **Project Loop:** Goal `G-0055`, Task `T-0119`, Feature `F-0061`
- **DB schema:** remains 8

## Goal

Materialize the 16 frozen arm packets into isolated, executable project roots
before independent Cockpit sessions start. Setup cost and setup context must be
outside the measured arm, and both conditions of a pair must receive equivalent
state.

## Scope

1. Add a standard-library preparation script that consumes only the hash-bound
   arm-packet manifest and produces one isolated root/brief per arm.
2. Resolve every frozen setup operation to reviewed commands or internal
   service calls. Do not write SQLite directly.
3. Use the arm commit's runtime for initialization and orientation. Verify the
   checked-out source commit before setup.
4. For the mixed historical/current proof case, generate synthetic legacy
   state using released public PCL commands, then migrate through supported
   commands. Do not copy the canonical repository's private `.project-loop`
   state into the evaluation.
5. Generate resume packets before the measured consumer session and bind them
   to the frozen Task/Goal IDs.
6. Produce a deterministic manifest containing root, source commit, entity ID
   mapping, setup command log, packet hashes, and the exact consumer brief.

## Acceptance

1. Exactly 16 distinct roots exist and match the 8x2 prepared-arm manifest.
2. IDs match the frozen digit grammar and role mapping for every case.
3. Baseline/treatment roots in a pair are semantically equivalent before the
   measured arm, apart from runtime-generated timestamps/event IDs.
4. Human decisions and draft Stories are created through PCL commands and
   remain unresolved/unapproved.
5. No setup command is counted as an arm tool call or exposed as consumer
   reasoning guidance.
6. Missing source commits, unexpected IDs, hash drift, unsupported setup ops,
   or failed commands stop before any Cockpit arm launches.
7. Focused tests, Ruff, and a 16-root dry-run/materialization smoke pass.

## Invariants

- No direct SQLite writes, schema/dependency changes, model calls, telemetry,
  generated-dashboard edits, or `.project-loop` mutation in the canonical
  repository.
- Generated roots and packets live outside the repository and are disposable.
- Frozen prompts, oracles, metrics, thresholds, and arm assignments are not
  changed by this task.
