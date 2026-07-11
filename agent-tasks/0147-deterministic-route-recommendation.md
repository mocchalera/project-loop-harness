# 0147: Deterministic route recommendation

- **Status:** Done; human-approved 2026-07-11
- **Milestone:** v0.4.2 Adaptive Entry
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** 0146
- **Parallel-safe with:** none
- **DB schema:** remains 8

## Goal

Produce a read-only `route-recommendation/v1` from explicit, normalized inputs
without an LLM. The UX profile is `direct`, `discover`, or `assure`; reason
codes and risk facts remain visible.

## Contract

Required fields: contract version, policy version, target, input digest,
profile, risk level, normalized signals, and stable reason codes. Policy axes
and override state are not part of this contract.

## Scope

- Pure ordered-rule resolver with documented tie breakers.
- Signal catalog for acceptance completeness, ambiguity, requested paths,
  dependency/migration/auth/security surfaces, deterministic checks, and
  unknown data.
- Read-only `pcl route recommend --target ... --json`.
- Optional explicit `--record` stores the exact recommendation as Evidence and
  appends one event/outbox record.
- Additive start output only when the caller explicitly requests routing.

## Invariants

- Same normalized inputs and policy version yield byte-equivalent decision
  content.
- Model self-assessment is not a risk-lowering signal.
- Missing information is explicit and cannot silently become Direct.
- High-risk signals cannot be erased by lower-risk signals.
- Read-only default does not mutate DB, events, outbox, or filesystem.

## Acceptance criteria

Fixtures prove clear low-risk -> Direct, missing acceptance/unverified cause ->
Discover, and auth/migration/destructive scope -> Assure. Linux/Windows path
normalization, tie-break ordering, unknown input, JSON stdout purity,
determinism, explicit record, and old start snapshots are covered.

## Non-goals

Policy axes, enforcement, override, model selection, semantic code analysis,
or automatic workflow launch.
