# Priority reset — 2026-07-13

## Decision

Adoption / Distribution now precedes additional Council feature work and the
v0.5.1 Trace milestone. The product has enough internal control-plane depth to
test its market-facing value; adding more concepts before new-user evidence
would increase complexity without resolving the current bottleneck.

This reset adopts the review in
`docs/reviews/2026-07-13-business-technical-review.md` and the factual limits in
the offline Council adoption outcome.

## Ordered priorities

| Order | Priority | Work | Exit condition |
|---:|---|---|---|
| 1 | P0 done | 0163 Adoption-first release readiness | 30-second README, five-minute setup, coexistence contract, stability policy, time-safe tests, full verification |
| 2 | P0 next | v0.5.0 local release candidate | version/docs/package surfaces agree; source, wheel, and sdist smokes pass; independent review complete |
| 3 | P1 | External-feedback launch packet | demo and Japanese/English post drafts are reviewable; publication remains human-approved |
| 4 | P1 | Maintainer entry hardening | dev environment can identify stale editable installs; CLI split plan freezes behavior before refactor |
| 5 | P2 | Scale baseline and event-log policy | documented file/event ranges, benchmark fixture, rotation/compaction design note; no premature implementation |
| 6 | P2 | v0.5.1 Trace & Efficient Handoff | claim-bound handoff and cross-session resume are measured after Adoption evidence exists |

## Council disposition

- Core boundary, offline E2E, failure handling, provenance, and 12-case offline
  evaluation are complete enough for an experimental opt-in surface.
- The human outcome is `continue experiment`, not adopt-by-default.
- Real-provider Council work remains parked until a separate hash-bound
  authorization permits the provider, data class, budget, and expiry.
- No Council runner, default change, telemetry, or publication is implied by
  this priority reset.

## Why this order

1. A new user cannot value architecture they cannot discover or understand.
2. Stability boundaries reduce adoption risk before external users arrive.
3. Current test and Project Loop warning debt must not be hidden by a release.
4. External feedback should determine whether maintainability and scale work
   needs promotion, rather than speculative feature growth.
5. The core product remains the guarded state machine; Adoption changes the
   path into it, not the architecture.
