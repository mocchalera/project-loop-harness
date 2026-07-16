# v0.5.2 Adoption Proof plan

- **Status:** Active
- **Activated:** 2026-07-16
- **Decision source:** owner instruction to proceed with the adoption-first direction
- **Release boundary:** implementation and internal verification do not publish a release

## Outcome

A new user can understand the product, inspect and initialize a real repository,
and reach one evidence-backed completion without the maintainer operating the
loop for them. The project can show observed outcomes, not proxy activity.

## Ordered stages

1. **Config-ready initialization.** Extend the existing `pcl init --dry-run`
   entry point for Python and Node detection. Keep it read-only before apply,
   preserve existing config, and disable unknown commands explicitly.
2. **Public entry compression.** Keep README at 200 lines or fewer; lead with
   the outcome, real dashboard, install/init, agent prompt, and five operator
   moments. Move reference depth to curated docs.
3. **External first-use cohort.** Observe five users across at least three real
   repository types with the frozen protocol in `docs/adoption-proof-v0.5.2.md`.
4. **Friction repair.** Rank observed blockers by failed activation, frequency,
   and severity. Fix the top three; do not substitute feature expansion.
5. **Release decision.** Prepare v0.5.2 only if code quality is green and the
   cohort result is reported honestly. A missed threshold is a learning result,
   not permission to relabel internal evidence as adoption.

## Allocation until the cohort closes

- 70% activation and user observation;
- 20% maintenance and reliability;
- 10% bounded experiments.

## Deferred

- Council, Trace, Intent, dashboard, or MCP surface expansion;
- hosted backend, cloud sync, telemetry, and paid services;
- standalone binary work before install friction is observed;
- releases for internal refactor slices;
- adoption claims from PyPI downloads, GitHub clones, or CI traffic.

## Exit conditions

1. Median install-to-healthy-setup time is five minutes or less.
2. At least four of five participants reach a valid completion packet within
   one session and 30 minutes.
3. There are zero human-gate or safety-boundary violations.
4. At least two participants voluntarily reuse the tool within seven days.
5. Maintainer intervention is at most one per participant.
6. The result, including misses and sample limitations, is preserved as
   reviewable evidence before any adoption claim.
