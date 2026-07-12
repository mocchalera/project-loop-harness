# 0156: Deterministic read-only Profile request preparation

- **Status:** Done
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P0
- **Size:** L
- **Dependencies:** 0155
- **DB schema:** no change

## Goal

Build `profile-run-request/v1` from current PLH state without invoking a runner
or mutating project state.

## Scope

- Add `pcl profile prepare <id> --target type:ID [--brief E-ID] [--output]`.
- Resolve one healthy Work Brief candidate, effective route, adaptive policy,
  context payload, and linked Evidence hashes.
- Allow an unapproved Brief for Discovery but label it; require `--brief` when
  candidates are ambiguous.
- Bind manifest, project fingerprint, target, Brief, route/override, policy,
  context, limits, data policy, and request digest.
- Compute a stable request-basis digest. Without matching authorization,
  paid/network policy returns a candidate request plus `human_required` and
  does not claim permission.
- Normalize generated time and receipt-age presentation fields using the exact
  0154 pointer list while retaining underlying receipts and source hashes.
- Compute the project fingerprint from local root/config/schema/Git inputs and
  emit only the digest plus project basename.

## Invariants

- No SQLite, event, outbox, Evidence, report, dashboard, or route mutation.
- `--output` writes only the named request file.
- No absolute project root, dashboard HTML, database, secret, or transcript.
- Route mismatch fails and points to existing audited override commands.

## Acceptance

1. Reverse-order data reads and different wall-clock execution produce the same
   basis digest when semantic state is unchanged.
2. Before/after DB, JSONL, Evidence, report, and dashboard hashes are unchanged.
3. Missing/ambiguous Brief, route mismatch, approval, and context-budget errors
   are stable and repairable.
4. Root path and secret sentinels are absent.
5. Paid/network policy cannot become allowed without a matching authorization
   event; the offline path remains fully usable before 0159.
6. Targeted and full suites pass.
