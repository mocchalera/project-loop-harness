# 0159: Decision proposal selection and paid/network authorization

- **Status:** Planned
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P0
- **Size:** L
- **Dependencies:** 0158
- **DB schema:** remain 8; existing Decision is authoritative

## Goal

Atomically reduce a `needs_human` bundle to 1..3 existing Decisions and bind a
human selection to immutable proposal bytes and factual provenance.

## Scope

- Add connection-scoped Decision mutation helpers for Profile ingest.
- Create Decisions and Evidence links in the same transaction as bundle ingest.
- Bind proposal ID/path/hash, candidates, recommendation, target, and bundle
  Evidence in events.
- Add `pcl decision proposal show/select` as thin projections over existing
  Decision state and immutable Evidence.
- Require human actor, recorder/source provenance, reason, and an override
  reason for a non-recommended candidate.
- Add explicit `pcl profile authorize` over a candidate request. Copy the
  request as immutable Evidence and append a basis-digest-bound
  `profile_run_authorized` event using existing `approval-provenance/v1`.
- Verify provider/data scope, cost cap, expiry/revocation condition, current
  basis digest, Evidence hash, and human source before final prepare.
- Guard legacy `pcl decision resolve/waive`: proposal-linked Decisions return
  `decision_proposal_command_required`; ordinary Decisions remain compatible.

## Invariants

- Recommendation never auto-resolves a Decision.
- Agent/system actor cannot satisfy the gate.
- Original bundle/proposal is never edited.
- Same selection replay is idempotent; conflicting replay fails closed.
- Resolving all proposals does not approve a revised Work Brief.
- Authorization never invokes a provider and becomes stale after any semantic
  request-basis change.

## Acceptance

1. needs-human ingest atomically creates 1..3 Decisions and all binding events.
2. `pcl next --json` returns the open Decision using existing priority.
3. Hash drift, agent-only actor, missing source, missing override reason, and
   candidate conflict all fail with zero mutation.
4. Existing decision commands remain compatible.
5. Agent-only authorization, stale basis, expanded provider/data scope, expired
   approval, and missing source all fail closed.
6. Legacy resolve/waive cannot close a proposal-linked Decision and produces
   zero mutation; ordinary Decision tests remain unchanged.
7. Dashboard/report changes, if any, are additive and factual.
