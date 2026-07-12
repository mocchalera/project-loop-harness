# 0154 Council contract freeze — Claude Fable review

**Reviewer:** Claude Fable 5, high effort, via AGI Cockpit  
**Cockpit task:** `8803833e`  
**Date:** 2026-07-12  
**Mode:** independent review only; no edits or PCL mutation

## Initial verdict

Conditionally approved. The boundary design and schema structure were sound,
but the reviewer independently recomputed and rejected placeholder/inconsistent
bundle, manifest, request, and artifact digests. It also required an explicit
authorized re-prepare request-ID rule before contract freeze.

## Changes made from the review

- Recomputed manifest, request basis/final, Council request-ref, artifact, and
  bundle digests and sizes from the frozen canonical/exact-byte rules.
- Added regression tests that recompute every digest and cross-reference.
- Kept `request_id` in the basis and required authorized re-prepare to reuse
  the bound candidate ID.
- Made `next_action.safe_to_run` always `false`.
- Froze request-policy to authorization-data-class mapping and provider/cost
  coverage.
- Strengthened path syntax, added a dot-segment negative fixture, and tested
  empty/dot/trailing segment rejection.
- Froze mediated human-recording semantic checks for task 0155.
- Added the Council run request-ID pattern.
- Recorded the project-fingerprint dictionary-attack risk, why HMAC is deferred
  for the read-only/schema-8 MVP, and its revisit condition.

## Final verdict

Claude Fable independently reran digest/schema/tests and approved task 0154 for
contract freeze. Acceptance 2–8 were confirmed. Acceptance 1 remains the
intentional human gate: ADR-005 must receive an explicit Accept, Modify, or
Reject outcome before task 0155 begins.

The reviewer recommends **Accept** because the earlier Modify conditions were
fully reflected. Remaining non-blockers are commit hygiene, harmless duplicate
`safe_to_run=false` schema constraints, and ensuring the documented semantic
checks land in task 0155.

