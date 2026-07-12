# 0162: Council evaluation baseline and adoption gate

- **Status:** Planned
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P1
- **Size:** L
- **Dependencies:** 0161
- **DB schema:** no change unless separately approved

## Goal

Compare Direct/single-model work with Council work before changing any default
recommendation.

## Scope

- Freeze a 10..20 task cohort before result inspection: clear, ambiguous,
  repository analysis, migration/auth/security, and product decisions.
- Measure human review time/decisions, first-pass checks, rework, design drift,
  escaped defects, token/cost/latency, schema failures, and safe stops.
- Track risk prediction to observed outcome and unnecessary clear-task Council
  insertion.
- Produce a human Decision: adopt, adopt with constraints, continue experiment,
  or reject.

## Invariants

- Failed and budget-exhausted runs remain in the sample.
- Baseline/success criteria do not change after results are seen.
- Model ratings are not facts without source and sample size.
- No telemetry, hosted analytics, leaderboard, or vendor selection in Core.

## Acceptance

1. Cohort, baseline, exclusions, and success thresholds are immutable first.
2. Results cover quality, human attention, cost, latency, and failure modes.
3. Invalid/partial/budget safe-stop rate is 100%.
4. Human owner records the adoption outcome and constraints.
5. Any default change is a separate narrowly scoped task.

