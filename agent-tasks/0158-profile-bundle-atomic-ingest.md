# 0158: Atomic Profile bundle Evidence ingest and idempotency

- **Status:** Planned
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P0
- **Size:** L
- **Dependencies:** 0157
- **DB schema:** remain 8; stop if a migration becomes necessary

## Goal

Persist one validated external bundle as immutable target-linked Evidence with
an outbox event, zero partial mutation, and exact replay idempotency.

## Scope

- Add a dedicated directory-bundle staging/copy service for validated external
  inputs without changing the existing permissive adhoc outside-root policy.
- Re-hash staged bytes before beginning the DB mutation.
- Insert one `profile_output_bundle` Evidence, target link, and
  `profile_output_ingested` event in one transaction.
- Store profile/request/bundle metadata in the immutable manifest and event.
- Implement exact replay and same-ID/different-digest conflict behavior.
- Require `--accept-failed --summary` to persist a failed bundle.
- Extend `audit._check_evidence` to detect finalized unreferenced Profile bundle
  directories left by rename-before-commit crashes and return report/quarantine
  guidance without automatic deletion.

## Invariants

- Rejected or interrupted pre-commit input leaves zero rows/events and no
  staging residue.
- Existing Evidence semantics and adhoc path restrictions do not weaken.
- Stored artifacts are immutable and only listed files are authoritative.
- JSONL projection remains recoverable through the existing outbox/audit path.

## Acceptance

1. A valid non-human bundle adds exactly one Evidence, one target link, and one
   ingest event.
2. Exact replay returns original IDs with zero mutation; conflicts fail.
3. Crash injection covers copy, pre-rename, post-rename/pre-commit, and outbox.
4. Audit detects Profile temp files and finalized unreferenced bundle
   directories; cleanup remains explicit and never guesses durable state.
5. Source, wheel, and sdist ingest tests pass without migration/dependency.
