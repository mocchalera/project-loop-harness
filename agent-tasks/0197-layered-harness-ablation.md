# 0197: Layered Harness Minimization Ablation

- **Status:** Complete (`modify`; Phase 5 not authorized)
- **Milestone:** Harness Minimization Phase 4
- **Priority:** P0
- **Size:** L
- **Dependency:** 0193 through 0196 integrated and green
- **Project Loop:** Goal `G-0055`, Tasks `T-0115` through `T-0117`, Feature `F-0061`, Story `US-0059`, Tests `TC-0129` through `TC-0131`
- **DB schema:** remains 8

## Goal

Measure whether the target-bound, prose-minimized harness improves agent work
without weakening acceptance, routing, proof, resume, or human gates. The
experiment must be frozen before execution and must retain failed and
safe-stopped cases in the denominator.

## Frozen comparison

- Baseline: commit `7fa22b2`, immediately before target-bound runtime routing.
- Treatment: reviewed integration commit `5ce17ec`, containing 0193 through
  0196.
- Eight paired cases, with one baseline and one treatment run per case:
  - three single-session routing/proof cases;
  - three resume/handoff cases;
  - two human-gate cases.
- Each pair uses the same literal objective, fixture state, acceptance oracle,
  agent runtime/model, and allowed context. Arms run in independent sessions.

## Scope

1. Add a hash-pinned cohort manifest and runbook under `docs/evaluation/`.
2. Add deterministic fixtures and tests that freeze all eight case IDs,
   prompts, layers, arm commits, expected outcomes, and metric definitions.
3. Add a dependency-light offline evaluator that accepts recorded result JSON,
   rejects missing/duplicate/mutated cases, and never invokes a model or edits
   project state.
4. Execute all 16 arms through Cockpit tasks under the user's explicit
   delegation request. Preserve raw task IDs and reviewer-checkable result
   records; do not claim external adoption.
5. Produce a machine aggregate and an evidence report with every failure,
   intervention, safe stop, missing cost signal, and limitation.

## Metrics

Quality metrics are paired booleans or counts:

- acceptance success;
- target/route accuracy;
- resume/handoff accuracy;
- current-proof classification accuracy;
- human-gate integrity;
- unintended mutation count;
- human intervention count.

Cost metrics are recorded per arm:

- tool/command calls;
- wall-clock seconds;
- input and output tokens when the runtime exposes trustworthy usage;
- loaded Skill bytes as a deterministic context-size measure.

Unavailable provider token usage is `null`, never estimated. Token conclusions
require complete paired coverage; other metrics remain reportable.

## Recommendation rule

Return `proceed` only when treatment has no paired regression in any quality or
safety metric, no critical gate violation, and strictly improves at least one
fully observed paired cost metric without worsening another beyond the frozen
tolerance. Otherwise return `modify` or `stop`. Thresholds and tolerances may
not change after results are observed without a new cohort ID and full rerun.

## Acceptance

1. The cohort contains exactly 8 cases split 3/3/2 across the required layers
   and exactly 16 independent arm records.
2. Baseline and treatment commits, prompts, fixtures, oracle, and thresholds
   are frozen and hash-checkable before the first run.
3. Failed, contaminated, missing, and safe-stopped cases remain visible and in
   the denominator.
4. The evaluator is deterministic, offline, fail-closed on malformed input,
   and covered by positive and negative tests.
5. The report distinguishes measured tokens from unavailable token data and
   makes no unsupported efficiency claim.
6. Full pytest, Ruff, strict validation, render, and current-repository dogfood
   commands pass after adding the evaluation artifacts.

## Stop conditions

- Stop an arm on forbidden context, fixture drift, destructive action, or an
  unrecordable human-gate bypass.
- Do not implement Phase 5 when the aggregate is `modify` or `stop`.
- Do not add telemetry, paid-service dependencies, or a new harness mode.
