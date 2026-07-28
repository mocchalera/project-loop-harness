# 0217 Target Attach and Routing Validation

## Scope

P0-4 adds one internal `routing-target/v1` resolver and connects explicit
Task/Goal selection across `pcl start`, target-bound `pcl next`, Task read, and
finish planning/emission.

Implementation commit:

- `3c6c019` — target attach, scoped blockers, shared resolver, regressions,
  Skill copies, and operator documentation

Tracked PCL work:

- Goal `G-0067`
- Task `T-0144`
- Feature `F-0073`
- Story `US-0071`
- Tests `TC-0151` through `TC-0154`

No database migration or dependency was added.

## Contract

`routing-target/v1` resolves a caller-supplied Task or Goal without inferring a
replacement. It returns the exact target, parent Goal when present, and a
deterministic set of references that can legitimately block that target.

- missing and wrong-type targets fail with typed input errors;
- an asserted Task/Goal parent mismatch fails instead of being repaired or
  guessed;
- a Task that references a missing parent Goal fails closed;
- target-bound Decisions must declare a blocking reference that intersects the
  resolved scope;
- target-bound Defects must be linked to the Task, or to a child Task when the
  selected target is a Goal;
- Task terminal readiness remains owned by `terminal-readiness/v1`.

The existing public `target_binding` keys remain `target_type`, `target_id`, and
`source`. Finish dry-run exposes the same binding additively.

## Start attach

`pcl start "<intent>" --task T-XXXX` reuses the Task and its parent Goal.
`--goal G-XXXX` reuses the Goal and creates only one child Task. New work and
attach work leave the selected Task visibly `in_progress`.

Goal/Task creation or Task activation, start receipt Evidence, optional Skill
provenance, `work_started`, and their outbox records share one authoritative
mutation transaction. A fail-first rollback test injects a receipt failure
after Task selection and proves that status, Evidence, event, outbox, and JSONL
counts remain unchanged.

The no-target `pcl-start/v1` response fields and stable JSON fixture are
unchanged. Its Task state intentionally changes from `todo` to `in_progress`;
lifecycle and resume expectations were updated to reflect the active-state
contract.

## Test-first evidence

The initial targeted run produced six expected failures:

```text
6 failed
```

The failures covered missing start attach flags, non-atomic activation,
unrelated Decision interception, unbound cross-Goal ambiguity, and missing
finish binding/readiness.

After implementation:

- `tests/test_start.py`: `16 passed`
- `tests/test_next_actions.py`: `30 passed`
- `tests/test_finish.py` plus finish workspace: `24 passed`
- Skill and shared resolver set: `31 passed`
- full suite: `1218 passed, 1 skipped in 383.20s`
- `ruff check .`: success
- `git diff --check`: success

## Live project dogfood

Before P0-4, `pcl next --target T-0143 --json` returned external campaign
Decision `DEC-0014` with `routing_scope=project_gate`.

After P0-4:

- `pcl next --target T-0144 --json` returned
  `pcl context pack --task T-0144 --json`;
- `pcl start "Continue P0-4 target attach and routing scope" --task T-0144
  --json` created only Evidence `E-0603` and event `EV-1B43DE29826E`;
- Goal `G-0067` and Task `T-0144` were not duplicated;
- `pcl task read T-0144 --json` retained `in_progress`;
- finish dry-run retained Task `T-0144`, parent Goal `G-0067`, explicit
  `target_binding`, and the existing blocked `terminal-readiness/v1` result.

## Compatibility and residual boundaries

- Targeted routing no longer gives unrelated project gates precedence.
- A directly blocking Decision and a related Defect still preempt target work.
- Unbound single-Goal ordering remains unchanged. Cross-Goal actionable
  ambiguity now returns `select_target` before an unrelated global gate.
- Existing finish packet and completion outcome schemas are unchanged.
- Story `US-0071` remains draft and Tests `TC-0151`–`TC-0154` remain planned;
  implementation authorization was not treated as semantic Story approval.
- Finish dry-run still returned 261 change rows from the current working tree;
  summary/pagination and machine-state exclusion remain P0-5 work.
- Reattaching an already active Task records another start receipt/event.
  Retry idempotency remains a P0-5 design item.
