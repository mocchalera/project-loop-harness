# 0163: Adoption-first release readiness

- **Status:** Done; Claude Fable approved and full regression passed on 2026-07-13
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** M
- **Dependencies:** 0160; 0162 offline adoption outcome
- **DB schema:** no change

## Goal

Turn the proven local control plane into a product a new multi-agent operator
can understand in 30 seconds, initialize in five minutes, and continue using
without personally running routine `pcl` commands.

## Source

- `docs/reviews/2026-07-13-business-technical-review.md`
- Cockpit task `524a3d14`
- `docs/evidence/0162-human-adoption-outcome.md`

## Scope

- Rebuild the top of README as a three-layer adoption path: 30-second value,
  five-minute first value, then detailed reference.
- State the safe coexistence contract for existing `AGENTS.md`, `CLAUDE.md`,
  `.gitignore`, and `pcl.yaml` files.
- Publish an alpha stability policy covering versioned JSON contracts, typed
  error codes, migrations, and explicitly unstable/internal surfaces.
- Freeze the operator promise that routine loop CLI is agent-owned after the
  one-time installation and initialization step.
- Remove the fixed-date expiry from Council authorization tests so the release
  suite remains valid after 2026-07-13.
- Synchronize the active backlog and roadmap so Adoption precedes additional
  Council investment and v0.5.1 feature expansion.

## Invariants

- No publication, external post, telemetry, provider execution, paid service,
  default Council activation, dependency addition, or database migration.
- Direct remains the clear-task default. Council remains opt-in and advisory.
- Stability claims must be narrower than the behavior already enforced by
  contracts and tests.
- Existing detailed documentation remains available; the README change alters
  information order, not runtime semantics.
- Tests must not weaken the production expiry guard.

## Acceptance

1. The Cockpit review is preserved in a repository review file with provenance.
2. README presents the 30-second pitch, five-minute setup, and agent-owned
   routine flow before implementation details.
3. The Adoption Guide explains inspect-first coexistence and the exact `--force`
   boundary.
4. The stability policy distinguishes protected public contracts from text,
   dashboard markup, internal Python APIs, and physical SQLite layout.
5. Council authorization tests use a future expiry relative to their fixed
   request time or current CLI time and still prove expired input is rejected.
6. Documentation contract tests, targeted tests, lint, and the full suite pass.
7. Claude Fable reviews the milestone before closure.

## Deferred follow-ups

- v0.5.0 release-candidate build and publication decision.
- Public launch article and demo recording; publication is a human gate.
- `cli.py` / `commands.py` staged module split.
- Large-repository and long-lived event-log performance baseline.
- At least ten paired real-provider Council cases, after separate authorization.
