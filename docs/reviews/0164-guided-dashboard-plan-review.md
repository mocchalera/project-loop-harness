# 0164 guided dashboard plan review

Date: 2026-07-13

Reviewer: Claude Fable through AGI Cockpit task `e57c72b1`

Review mode: read-only product and technical plan review. The reviewer was
instructed not to edit files, mutate Project Loop state, commit, push, or
approve human Story semantics.

## Verdict

**Approve with required amendments.** The slice addresses the reported
operator friction using existing derived state and does not require making
dashboard HTML a machine source of truth or coupling Core to Cockpit.

## Required findings adopted

1. `Done` must be deterministic and evidence-backed. There is no honest
   "since last viewed" boundary, and reason-only Task completion must not be
   presented as verified success.
2. The operator summary stays HTML-only. `dashboard-data/v1` remains unchanged
   because its exact top-level key set is a protected contract and agents
   already have JSON state surfaces.
3. Japanese summary sentences are composed from structured state and localized
   templates rather than embedding English reason or summary strings.
4. Progressive disclosure uses native `<details>/<summary>` with no script,
   and existing evidence fragment anchors remain reachable.
5. The Skill distinguishes silent routine rendering from presenting the
   dashboard only at four meaningful review moments.

## Advisory findings adopted

- Reuse exactly the Skill orientation vocabulary: `Now`, `Done`, `Next`,
  `Human needed`, plus `Risks`.
- Demote the generated-file rule banner below the operator summary.
- Keep the global dashboard locale default English; configure this Japanese
  repository with `dashboard.locale: "ja"` and preserve `--locale en` override.
- Reuse existing Skill parity tests instead of adding a second parity system.
- When a plan-stage dashboard is sparse, the agent should say that nothing
  needs the operator yet instead of directing them to empty tables.

## Recommended implementation order

1. Persist the repository locale and dogfood normal Japanese rendering.
2. Implement pure HTML operator-summary derivation and localized templates.
3. Apply native progressive disclosure without removing navigation targets.
4. Update all bundled Skill copies and existing parity coverage.
5. Update README and Adoption Guide.
6. Run automated and Cockpit visual checks, then request implementation review.

