# 0159 Profile Decisions and authorization validation

**Date:** 2026-07-12

**SQLite schema:** 8, unchanged

**Provider execution:** none

## Decision proposal flow

- A `needs_human` bundle creates 1..3 open Decisions, one dedicated Evidence
  link and one `profile_decision_proposed` event per proposal, atomically with
  the bundle Evidence ingest.
- Event payloads bind bundle ID/digest, Evidence ID, artifact ID/path/hash,
  proposal ID, candidate IDs, recommendation, and target.
- `proposal show` reconciles Evidence manifest/files and re-hashes the exact
  bytes it parses.
- `proposal select` requires a human actor plus recorder/source provenance.
  Non-recommended choices require an override reason; `--decline` records an
  explicit all-candidates rejection.
- Same-selection replay is zero mutation. A different replay conflicts.
  Legacy resolve/waive return `decision_proposal_command_required` without
  affecting ordinary Decisions.

## Authorization flow

- Candidate preparation explicitly records requested network/provider,
  repository data class, paid-service flag, budget, and currency while keeping
  `authorization: null` and never executing a provider.
- `profile authorize` rejects agent/system actors, missing provenance,
  provider/data/cost/currency under-scope, past expiry, and stale semantic
  basis before mutation.
- The exact candidate bytes become immutable `profile_run_candidate` Evidence.
  One preallocated event ID is shared by the event and embedded
  `approval-provenance/v1` receipt.
- The authorized request is derived from candidate Evidence bytes, reuses the
  candidate request ID and basis digest, and changes only authorization and
  final request digest.
- Exact authorization replay re-emits the same request with original
  Evidence/event IDs. Ingest also checks expiry, revocation event, receipt/event
  equality, current basis, and Evidence hash.
- Audit reconciles candidate Evidence bytes with the authorization event.

## Verification

```text
$ ruff check .
All checks passed!

$ PYTHONPATH=src pytest -q tests/test_profile_ingest_dry_run.py \
    tests/test_profile_prepare.py tests/test_decisions.py \
    tests/test_event_outbox.py tests/test_distribution.py
81 passed

$ PYTHONPATH=src pytest -q
928 passed, 1 skipped
```
