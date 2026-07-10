# 0143: Dedicated terminal link repair commands

- **Status:** Approved implementation slice
- **Milestone:** v0.4.1 Integrity Migration
- **Priority:** P1
- **Estimated size:** L
- **Dependencies:** 0142 (repair-plan action model)
- **Parallel-safe with:** none of 0144–0145; shared `cli.py`, `validators.py`, and Evidence services require a serial merge
- **DB schema:** remains 8

## Problem

The v0.4.0 same-status contract deliberately makes repeated terminal commands
no-ops. Consequently, rerunning `pcl test pass` must not be overloaded to
repair a missing Story or Evidence link on an existing passing Test. Operators
need an explicit, narrow, audited path for relationship repair that does not
replay the lifecycle transition or rewrite historical Evidence.

## Goal

Add dedicated Test and Evidence link commands that validate the complete
relationship before mutation, repair links atomically, and leave lifecycle
status and historical records untouched. Consume the 0142 action model to add
the only structural apply path for lifecycle repair.

## CLI contract

```text
pcl test link TC-0001 [--story US-0001] [--evidence-id E-0007] --summary "..."
pcl evidence link E-0007 --target test_case:TC-0001 --role acceptance --summary "..."
pcl repair lifecycle --apply-structural [--json]
```

`pcl test link` requires at least one of `--story` or `--evidence-id`. When both
are supplied, both changes are validated before one transaction commits. The
JSON response reports `changed`, before/after relationship values, the event
ID, and any stable warnings.

`pcl evidence link` accepts an existing Evidence ID, a parsed
`<target-type>:<target-id>` reference, a role, and an audit summary. It is a
generic link insert only for known schema-8 target types and compatible roles;
it does not silently update a Test's `evidence_id`. For a terminal Test
`acceptance` link, the stored Test pointer must already match, otherwise the
command returns a typed error directing the operator to `pcl test link`.

`pcl repair lifecycle --apply-structural` first builds the current
`lifecycle-repair-plan/v1` plan through 0142, selects only actions with
`classification: structural` and `safe_to_apply: true`, and dispatches their
public `action_kind` values through the internal link mutation service owned by
this task. Unknown action kinds, non-structural actions, or changed
preconditions fail closed. No command string from the plan is shell-executed.

## Validation rules

- Test, Story, Evidence, and target IDs must exist before mutation.
- A Story linked to a Test must belong to the same Feature. A passing Test may
  link only an `approved` or explicitly `waived` Story.
- Acceptance Evidence for a direct passing Test must be an allowed healthy
  hash-pinned Evidence type and target the same Test.
- Feature `acceptance` Evidence and completion-packet roles must satisfy the
  existing terminal guard predicates.
- Completion-packet links require a valid packet whose embedded target matches
  the requested target.
- Known exclusive target-bound roles reject an existing conflicting target;
  generic supporting links retain their existing many-target behavior.
- All requested relationships are checked before opening the mutation window,
  then re-checked inside it to prevent a time-of-check/time-of-use repair.

## Scope

- Add the parser and dispatch paths in `src/pcl/cli.py`.
- Add one internal relationship mutation service used by `pcl test link`,
  `pcl evidence link`, and structural lifecycle apply. The service may be
  organized through `src/pcl/stories.py` and `src/pcl/evidence.py`, but 0142
  remains read-only and does not import it.
- Extend `src/pcl/lifecycle_repair.py` only with the explicit
  `--apply-structural` consumer of the already-public 0142 plan model.
- Keep `src/pcl/validators.py` consistent with the write-side rules.
- Add direct and regression coverage in `tests/test_stories.py`,
  `tests/test_evidence_add.py`, and lifecycle validation tests where needed.
- Update recovery documentation and command help examples.

## Mutation and event contract

- One successful `pcl test link` call uses one transaction and appends one
  `test_links_repaired` event containing old/new Story and Evidence IDs plus
  the operator summary.
- One successful `pcl evidence link` call uses one transaction and appends one
  `evidence_link_added` event containing Evidence, target, role, and summary.
- One successful structural plan application re-checks every selected action
  inside one transaction and appends one
  `lifecycle_structural_repair_applied` event containing plan action IDs,
  action kinds, and before/after relationships.
- Repeating an exact existing relationship returns `changed: false` and adds no
  event or outbox row.
- Replacing the current Test Evidence pointer does not delete or mutate the
  previous Evidence row or historical `evidence_links`; the event makes the
  pointer change reviewable.

## Invariants

- `pcl test pass` and every other same-status terminal call remain no-ops; they
  do not acquire hidden repair behavior.
- Link commands never change status, `created_at`, prior transition events,
  Evidence content/hash, Verification, Decision, or approval state.
- Any invalid or conflicting input produces a typed error and zero domain,
  event, outbox, or JSONL mutation.
- A stale structural plan or changed relationship precondition fails with a
  typed error and zero mutation; partial batch repair is not observable.
- Structural apply never dispatches semantic, human-review, or unsupported
  actions and never executes plan command strings.
- Every mutation goes through application services and the event outbox; no
  operator-facing raw SQL path is added.
- JSON changes are additive. Schema 8, dependencies, and legacy flags remain
  unchanged.

## Non-goals

- Story approval/waiver, Goal verification, or lifecycle status repair.
- Link deletion, bulk relinking, or automatic conflict resolution.
- Treating mutable legacy path strings as terminal proof.
- Generic Verification targets or a schema migration.
- Changing the 0142 classification/action/sort contract.

## Acceptance criteria

- A same-Feature approved Story and healthy acceptance Evidence can repair an
  existing passing Test in one audited transaction.
- Cross-Feature Story, draft/review Story on a passing Test, missing/drifted
  Evidence, incompatible role, packet target mismatch, and exclusive-role
  target conflict each fail with zero mutation.
- A combined command cannot commit the Story half if Evidence validation fails.
- `pcl evidence link` refuses to create a half-repaired terminal Test when its
  `evidence_id` pointer differs.
- Exact reruns are event-free no-ops; changing a Test pointer preserves all old
  Evidence rows and links.
- Structural apply accepts only recognized structural `action_kind` values,
  is atomic and audited, and is an event-free no-op when the current plan has no
  applicable structural actions.
- Existing tests prove repeated `pcl test pass` remains a same-status no-op.
- Repaired direct and Workflow-backed fixtures satisfy the existing lifecycle
  validator without weakening its predicates.
- After structural apply and explicit operator execution of every semantic or
  human-review action in the supported synthetic fixture,
  `pcl validate --strict --json` passes.
- Targeted tests, full `pytest`, `ruff check .`, strict validation, and render
  pass.

## Evidence required to close

- Before/after Test and `evidence_links` JSON plus the single emitted event.
- Zero-mutation counts/hashes for every rejection case.
- Same-status and exact-link idempotency regression output.
- A complete 0142 plan → 0143 structural apply → explicit semantic actions →
  strict-pass transcript.
