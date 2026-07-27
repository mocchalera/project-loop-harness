# 0216 Shared Terminal Readiness Validation

## Scope

P0-3 adds one side-effect-free `terminal-readiness/v1` evaluator and connects
the current routing, finish, and lifecycle terminal paths without a database
migration, dependency addition, or `completion-packet/v1` shape change.

Implementation commits:

- `f946277` — shared readiness contract, adapters, projection, and regressions
- `63457ec` — compact Task list projection after dogfood output review

Tracked PCL work:

- Goal `G-0067`
- Task `T-0143`
- Feature `F-0072`
- Story `US-0070`
- Tests `TC-0147` through `TC-0150`

## Contract

The evaluator accepts normalized target requirements and returns:

- `ready`
- `ready_with_risk`
- `incomplete`
- `blocked`
- deterministically ordered reasons
- deduplicated exact next commands
- `terminal_allowed` and `requires_human`

Precedence is `blocked` over `incomplete`, `incomplete` over risk, and risk over
ready. Advisory observations remain visible without changing readiness.

## Connected behavior

| Surface | Shared readiness behavior |
| --- | --- |
| Feature lifecycle | Existing Story, Test, and Defect guards raise their existing typed error codes from the shared result. |
| `pcl next` | Passing Feature actions expose additive readiness; a linked Task whose approved Story and non-waived Tests are complete derives `ready_to_close` and routes to `pcl finish --emit-packet --task`. |
| `pcl finish` | Strict errors, failed checks, repository race/input mutation, target child state, Decision, Escalation, and budget feed the shared result before outcome selection. |
| Goal lifecycle | Goal close reuses the shared Task-child readiness result while preserving `goal_close_tasks_incomplete`. |
| Task read/list | `task read` exposes full readiness for linked Tasks; `task list` exposes only compact `derived_status` to avoid multiplying JSON volume. |

Low strict warnings yield `ready_with_risk` and retain terminal eligibility.
Error, unknown effect, invalid child state, or human gates do not.

## Test-first evidence

The first targeted run failed during collection with:

```text
ModuleNotFoundError: No module named 'pcl.terminal_readiness'
```

After implementation:

- terminal/routing/finish/lifecycle related regression set: `83 passed`
- compatibility failures found by the first full run:
  - representative `next` snapshot did not yet describe the additive field
  - legacy `completion_blockers` was accidentally broadened beyond its
    completion-policy meaning
- both were corrected by documenting the snapshot delta and keeping all shared
  reasons under `terminal_readiness`
- full suite at the implementation milestone:
  `1209 passed, 1 skipped`
- compact Task-list follow-up:
  `8 passed`
- `ruff check .`: success
- `git diff --check`: success

## Compatibility and residual boundaries

- `completion-packet/v1` outcomes and check shape are unchanged.
- Existing Feature done and Goal close typed error codes are unchanged.
- Existing `completion_blockers` remains completion-policy-specific.
- The current single cold finish attempt remains
  `finish_stability_record_only`; its non-reproducible observation is advisory.
  Compatible history lookup and reuse remain P0-5 work.
- Target-bound `next` can still be intercepted by an unrelated global Decision.
  That routing-scope defect remains assigned to P0-4.
- No Story was self-approved and no planned Test was promoted to passing as
  part of this implementation Evidence.

## Adopter monitoring

Cockpit task `81812d6f` reached `waiting_confirmation` with its Codex Goal
complete. Its latest report distinguishes an older accepted SHA from the final
accepted SHA and identifies the final review task and all-green CI as the
authoritative acceptance evidence. No external or adopter-task state was
changed by this monitoring task.
