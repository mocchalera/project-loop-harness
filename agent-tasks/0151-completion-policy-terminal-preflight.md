# 0151: Completion-policy adapter and terminal preflight

- **Status:** Done locally; verified; not committed
- **Milestone:** v0.4.3 Evidence Completeness
- **Priority:** P0
- **Dependencies:** 0150
- **DB schema:** remain 8; stop for human approval if a migration is needed

## Problem

PCL can validate durable proof without knowing whether a collaborating tool
classified the result as `prototype` or `complete`. It also permits Test
planning without a Story and only discovers the structural weakness later.

## Scope

- Define a domain-neutral `completion-policy/v1` with allowlisted JSON
  predicates; do not execute arbitrary expressions.
- Bind the policy, evidence-set receipt, required verdict artifact, and
  structured acceptance conditions to a Test preflight.
- Require `complete` when target policy says so; permit honest intermediate
  states when the acceptance contract only asks for a prototype.
- Under enforced policy, reject `pcl test plan` without `--story` before
  mutation. Preserve an advisory migration path for existing projects.
- Make every terminal rejection transactionally clean.

## Invariants

- Core contains no `mockup-to-code`, DOM, or web-specific branches.
- Policy evaluation is local, deterministic, JSON-only, and standard-library
  first.
- `--evidence-id` remains the canonical terminal-proof route.
- A complete external verdict does not override unresolved required failures.
- Existing valid direct Test transitions remain compatible.

## Non-scope

- Next-action priority changes.
- Human/agent approval authority.
- Third-party tool execution or report generation.

## Acceptance criteria

1. A `prototype` verdict is rejected when a Test requires `complete`.
2. A missing required verdict and an incomplete evidence set are rejected with
   zero Test, Feature, link, or event traces.
3. A complete verdict plus required passing reports permits the existing
   Evidence-ID-first terminal transition.
4. Enforced and advisory Story-link planning behavior is fixture-tested.
5. Schema, evaluator, inspect output, and packaged contracts are deterministic
   and backward compatible.
