# Claude Fable milestone review: tasks 0155–0157

**Date:** 2026-07-12

**Cockpit task:** `18188820`

**Reviewed commits:** `d2e71a6`, `13749aa`, `5fd9388`

**Verdict:** APPROVE WITH REQUIRED FIXES

## Direction and strengths

Claude Fable found the implementation strongly aligned with ADR-005:

- model-independent: built-in Profiles are data-only and PLH never executes a
  provider;
- local-first: no new runtime dependency and default requests forbid network
  and paid services;
- Evidence-first: Work Brief, route recommendation, and override Evidence are
  bound and rechecked by canonical hash;
- human-governed: `safe_to_run` is always false and paid/network authorization
  fails closed without human approval provenance.

Claude independently ran the full suite: 911 passed, 1 skipped.

## Required fixes and resolution

1. **Exact Decision counts for partial/budget-exhausted bundles.** The planner
   counted proposal artifacts as Decisions for `partial` and
   `budget_exhausted`, while task 0159 creates Decisions only for
   `needs_human`. Resolved by restricting planned Decision/link/event/outbox
   increments to `needs_human` and asserting exact per-status plans in tests.
2. **Unbounded request-controlled output limit.** The frozen request schema has
   no maximum, so a self-digested request could raise the artifact read/copy
   limit. Resolved without loosening the frozen contract: ingest now rejects
   requests above a local runtime ceiling of 2,000,000 bytes before artifact
   reads or hashes. The future atomic ingest must re-run validation and must
   not trust a prior dry-run result.

## Adopted guidance for task 0158

- Re-run the complete validation inside real ingest.
- Stage by copy, re-hash staged bytes, then atomically publish before the DB
  transaction commits.
- Add plan-versus-observed mutation delta tests for every accepted status.
- Preserve proposal artifacts for non-`needs_human` statuses as Evidence bytes
  without creating Decision rows.

## Optional follow-ups retained

- Treat dry-run/file-system TOCTOU as low risk, but close it in 0158 with
  copy-then-verify staging.
- Consider showing the accepted-failed mutation plan, computing prepare time
  once, promoting shared private helpers, and documenting Git-HEAD fingerprint
  freshness in later tasks.
