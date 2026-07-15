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
| 2 | P0 done | 0164 Guided dashboard review experience | agents present a localized simple view at meaningful milestones and explain what the operator should inspect |
| 3 | P0 done | 0173 v0.5.0 local release candidate | version/docs/package surfaces agree; source, wheel, and sdist smokes pass; independent review complete |
| 4 | P0 done | 0174 v0.5.0 publication closeout | public Release, release-triggered Actions run, PyPI artifacts, and clean public install are independently verified |
| 5 | P1 done | External-feedback launch packet | Zenn first-channel publication is verified; HN was explicitly skipped; later channels remain separately human-approved |
| 6 | P1 done | 0175 Maintainer entry hardening | dev environment identifies stale editable installs; CLI split plan freezes behavior before refactor |
| 7 | P2 done | Scale baseline and event-log policy | documented file/event ranges, benchmark fixture, rotation/compaction design note; no premature implementation |
| 8 | P0 next | v0.5.1 Trace & Efficient Handoff | claim-bound handoff and cross-session resume are measured through controlled two-repository dogfood without waiting for external participants |

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

## v0.5.1 activation amendment — 2026-07-15

The owner confirmed in Cockpit Ask `ask_8f99470fc206` that availability of three
external users is unknown. External-user recruitment is therefore removed from
the v0.5.1 start gate rather than allowing an unbounded wait to stall product
learning.

The replacement gate is controlled, operator-led evidence: at least 10 frozen
handoffs across two owned repositories and two independent sessions, including
cross-runtime/model cases when separately authorized. The milestone still
requires at least 80% resume success, safe stops for all intentionally broken
bindings, and zero critical trust-boundary violations. This evidence is product
dogfood, not market validation or an adoption claim.

The implementation plan and task split are in `docs/plan-v0.5.1.md` and the
numbered task files 0178 through 0183 under `agent-tasks/`. The three-person
first-use protocol remains available for a later Adoption review whenever
participants become available.
