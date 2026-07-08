# 0105: Evidence copy observability

Milestone: v0.2.4 Trust Patch
Priority: P2
Area: evidence
Origin: docs/project-loop-harness-v0.2.3-third-party-review.md P2-2
Depends on: 0102 (both touch src/pcl/evidence.py — start after 0102 merges)

## Problem

v0.2.3 serialized evidence ID allocation to fix a concurrency race. When
`evidence add --copy` copies large files, the copy work may extend the time a
SQLite write transaction/lock is held. We have no measurements, so we cannot
judge whether reserved-row or counter designs are ever needed. Observability
first, redesign only if data demands it.

## Scope

1. Measure and record, for `pcl evidence add --copy` invocations:
   - `copy_duration_ms` (wall time of the file-copy phase)
   - `copied_total_bytes`
   - `member_count`
   These go into the `evidence_added` event payload (additive fields) via the
   standard `append_event` path (both stores, per the 0089 lesson — no
   JSONL-only or SQLite-only side channels).
2. Where measurable without redesign, record lock-related diagnostics (e.g.
   time spent inside the write transaction) as an additive payload field; if
   it is not cleanly measurable, state so in the task output instead of
   adding invasive instrumentation.
3. Add a concurrent copy stress test: N parallel `evidence add --copy`
   processes against one project must all succeed deterministically with
   unique IDs (extend the existing 0101 race-test pattern).

## Invariants

- Timestamps/durations must not break determinism guarantees of existing
  contracts: duration fields live only in event payloads, not in receipts,
  context packs, manifests, or anything byte-compared by tests.
- ID allocation semantics are unchanged (serialized allocation from 0101 is
  kept as-is).
- Non-`--copy` `evidence add` behavior and payload shape are unchanged
  except for fields explicitly listed above being absent.
- No new tables, no migration.

## Acceptance

- `evidence add --copy --json` emits an event whose payload includes the three
  metrics; existing consumers/tests unaffected (additive-only).
- Concurrent stress test green and deterministic across repeated runs.
- Full `pytest` green; `pcl validate --strict --json` green after live copy
  operations in a scratch project.
