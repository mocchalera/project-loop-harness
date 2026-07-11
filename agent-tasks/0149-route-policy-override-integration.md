# 0149: Audited route/policy override and packet integration

- **Status:** Done; human-approved 2026-07-11
- **Milestone:** v0.4.2 Adaptive Entry
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** 0148
- **Parallel-safe with:** none
- **DB schema:** remains 8

## Goal

Record an explicit operator override while preserving the original
recommendation and policy resolution, then expose optional references through
context, completion, and handoff packets.

## Scope

- `pcl route override --target --profile --reason --actor` with dry-run/preview.
- Hash-bound references to separate original recommendation and resolution Evidence.
- One transactional domain mutation, event, and outbox record.
- Read-only current/effective route and override explanation.
- Optional additive packet/context fields and backward-compatible fixtures.

The accepted implementation records three Evidence rows and links in one
transaction: original recommendation, original resolution, and the override.
Only one aggregate `route_override_recorded` event/outbox pair is appended.

## Invariants

- Actor and non-empty reason are required.
- Override never deletes or rewrites original artifacts.
- Permission, destructive-operation, migration, and human-review floors remain
  non-overridable.
- Failure before commit leaves no DB/event/outbox/artifact trace.
- Old packet readers/fixtures remain valid.

## Acceptance criteria

Preview is zero-mutation; successful override is audited; forbidden downgrade
fails closed; original/effective views remain available; policy changes do not
mutate historical packets; context/finish/resume compatibility suites pass.

## Non-goals

Automatic override, enforcement of all axes, Replan, stale propagation,
Discovery Profile, or automatic model selection.
