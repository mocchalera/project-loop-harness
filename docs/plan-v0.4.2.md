# v0.4.2 Plan — Adaptive Entry

- **Status:** Local release candidate prepared; publication pending
- **Date:** 2026-07-11
- **Milestone:** M3 / Adaptive Entry
- **Project Loop target:** `G-0018` / `T-0035`
- **Basis:** `docs/growth-plan-v0.2.4-v0.5.md`, integrated roadmap M3,
  v0.4.1 integrity-migration results, and
  `docs/canonical-state-baseline-v0.4.2.md`

## Objective

Add an optional, deterministic entry layer that can represent a Work Brief,
recommend `direct` / `discover` / `assure`, explain the resolved policy axes,
and record an explicit override without changing the existing
`pcl start -> finish -> resume` default path.

The runtime remains local, dependency-light, model-agnostic, and advisory in
v0.4.2. It does not call an LLM, select a model, approve human gates, or turn
Work Brief into a first-class table.

## Activation corrections

The integrated proposal is useful but cannot be implemented literally:

1. Proposed `work-brief/v1` requires an embedded route even though route
   recommendation consumes the brief. The repo contract removes that cycle:
   Work Brief content is valid without a route and route output is a separate
   Evidence artifact linked by reference.
2. An immutable brief cannot be changed from draft to approved in place.
   Approval is a hash-bound event over immutable Evidence, not a rewrite of the
   artifact.
3. Proposed `route-decision/v1` requires all policy axes before the route-only
   slice exists. The repo splits `route-recommendation/v1` from
   `adaptive-policy-resolution/v1`.
4. The nested proposed YAML policy cannot be parsed by the current shallow,
   standard-library YAML readers. v0.4.2 uses versioned JSON policy input and
   adds no runtime dependency.

## Canonical tasks

| Repo ID | Scope | Dependency |
|---|---|---|
| 0146 | Immutable `work-brief/v1` Evidence contract and hash-bound approval | v0.4.1 |
| 0147 | Read-only deterministic `route-recommendation/v1` | 0146 |
| 0148 | JSON `adaptive-policy/v1` resolver and read-only explain surface | 0147 |
| 0149 | Explicit audited override and optional packet/context references | 0148 |
| 0149a | Two-repository dogfood and performance/integrity gate | 0149 |
| 0149b | v0.4.2 package/release preparation | 0149a |

Adjacent implementation slices are serialized. They overlap CLI registration,
contract packaging, Evidence links, context/resume rendering, and fixtures.

## Compatibility and state boundaries

- DB schema remains 8 for v0.4.2. A migration requires a separate human
  approval and is not implied by this plan.
- `pcl start "<intent>"` keeps its current output and mutation behavior unless
  an explicit brief/route option is passed.
- Recommendation and explanation are read-only by default. Persistence and
  override require explicit mutation commands.
- Old completion/handoff/context packet fixtures remain valid. New references
  are optional and additive.
- Work Brief assertions remain claims-not-facts. Approval means an authorized
  actor accepted the brief as the current execution input; it does not prove
  its assumptions.
- A policy override cannot lower non-overridable permission, destructive,
  migration, or human-review gates.

## Performance and product gates

- Same normalized input and policy version produce byte-equivalent output
  except for explicitly non-deterministic presentation metadata.
- Route resolution p95 target is below 50 ms on local fixture runs.
- Direct route adds no mandatory human step and does not require a Work Brief.
- No recommendation may claim that a strong model lowers verification risk.
- At least two repositories exercise clear/ambiguous/high-risk tasks.
- Dogfood records recommendation, override, outcome, confusion, and measured
  overhead without telemetry.

## Release gate

Before v0.4.2 publication:

1. `ruff check .` and the full pytest suite pass.
2. Python 3.10–3.13 CI and Windows locking smoke remain green.
3. Wheel, sdist, packaged schemas, and clean-install smoke pass.
4. Schema 8 is consistent with no pending migrations.
5. Strict doctor and strict validation succeed under the documented canonical
   advisory baseline.
6. Audit has zero new anomalies relative to the 14-item historical baseline.
7. All new mutations append an event/outbox record and have negative tests.
8. Human approval remains pending wherever historical meaning or policy
   authority is unresolved.

## Out of scope

Replan, stale propagation, verifier provenance enforcement, Discovery Profile,
automatic model/tool selection, provider pricing, hosted services, telemetry,
new first-class Intent/Option/Knowledge tables, and automatic semantic repair.
