# 0176: Scale baseline and event-log policy

- **Status:** Done; documentation/fixture slice only
- **Milestone:** Post-v0.5.0 maintainability
- **Priority:** P2
- **Size:** S
- **Dependency:** 0175 maintainer entry hardening
- **DB schema:** remains 8
- **Evidence:** `E-0375` (`docs/evidence/0176-scale-baseline-event-log-policy.md`)

## Goal

Measure the current file/event footprint, establish advisory scale bands, and
document safe future rotation/compaction boundaries before any runtime policy
is implemented.

## Scope

1. Record a dated repository snapshot with file sizes, event counts, entity
   counts, and the SQLite/JSONL relationship.
2. Add a deterministic synthetic benchmark manifest for smoke, maintainer, and
   growth workloads.
3. Document rotation and compaction invariants, recovery requirements, and
   explicit non-goals.
4. Add a small contract test that proves the fixture remains ordered and
   non-enforcing.

## Invariants

- No runtime rotation or compaction is implemented.
- No schema, dependency, telemetry, provider, or release change is made.
- SQLite remains authoritative; JSONL remains a rebuildable projection.
- Thresholds are advisory design inputs, not SLOs or automatic gates.
- The fixture contains synthetic, deterministic data only.
