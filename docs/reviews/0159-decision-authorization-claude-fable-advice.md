# Claude Fable design advice: task 0159

**Date:** 2026-07-12

**Cockpit task:** `18188820`, follow-up turn

## Adopted guidance

- Use immutable `profile_decision_proposed` events as the sole proposal-link
  marker for existing schema-8 Decisions.
- Keep `blocks_json` limited to supported task and Evidence refs; place
  artifact ID/path/hash, candidates, and recommendation in the binding event.
- Link bundle Evidence to each Decision using the dedicated
  `decision_proposal_source` role.
- Guard legacy resolve/waive by querying the proposal event inside the same
  mutation transaction.
- Provide an explicit all-candidates-declined path so human rejection does not
  leave an unresolvable blocker.
- Re-read and hash immutable proposal bytes before selection; update with
  `WHERE status = 'open'`; require human/source/recorder provenance and an
  override reason for a non-recommended candidate.
- Emit only `profile_decision_selected`, while fully populating the legacy
  Decision row so existing next/dashboard/report projections remain factual.
- Record created Decision IDs in immutable Evidence/event state so ingest
  replay returns original IDs without allocation.
- For authorization, preallocate the event ID, derive the authorized request
  only from stored candidate Evidence, preserve request ID/basis, and make
  output re-emittable by exact replay.
- Reuse existing actor/recording provenance helpers; validate fresh semantic
  basis, three-way basis agreement, scope, expiry, Evidence hash, event receipt,
  and a DB revocation event.

## Implementation choice

`pcl next` retains the existing Decision priority but suggests
`pcl decision proposal show ...` for proposal-linked Decisions, avoiding a
legacy resolve command that is deliberately guarded.
