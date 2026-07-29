# 0214: Non-HEAD Goal packet base routing

- **Status:** Complete; local RC correction verified
- **Milestone:** v0.5.5 release-candidate correction
- **Priority:** P0
- **Size:** S
- **Dependency:** completed Task 0212 Goal completion-packet close routing
- **Project Loop:** Task `T-0154`, Feature `F-0083`, Story `US-0087`,
  Tests `TC-0202`–`TC-0203`
- **Reproduction Evidence:** `E-0687`
- **DB schema:** remains 8

## Problem

Real v0.5.5 release-preparation dogfood emitted exact-goal completion packet
`E-0686` at HEAD `d64d38d` with explicit ancestor base `4ee1299`. The packet
repository identity exactly matched a current recapture using that recorded
base. Immediately afterward, however:

```text
pcl next --target G-0075 --strict --explain --json
```

recommended another approximately 13-minute finish instead of the exact
Evidence-bound close command.

`_latest_reusable_goal_completion_packet` validates the packet, but then calls
`capture_finish_repository_snapshot(paths)` without its recorded
`base_revision`. The recapture defaults to HEAD, so an otherwise current packet
with a non-HEAD base is falsely classified as stale.

## Story contract

For an explicitly bound direct-route Goal, the newest valid, healthy,
completed, low-risk packet is current when a repository recapture using the
packet's validated `repository.base_revision` exactly equals the packet's
repository identity.

When current, `pcl next --target` returns the existing agent-safe `close_goal`
action with the exact packet Evidence ID. An invalid/unresolvable base or
actual content drift retains the existing `emit_completion_packet` fallback.

## Minimal implementation

1. Resolve and validate the newest exact-goal packet through the existing
   shared completion-proof service.
2. Read only its validated `repository.base_revision`.
3. Pass that value to the existing shared
   `capture_finish_repository_snapshot` service.
4. Require exact equality with the packet repository object.
5. Return no reusable packet on invalid shape or `InvalidInputError`.

Do not duplicate Git hashing, modify packet v1, or weaken Evidence health,
latest-only resolution, target binding, low-risk acceptance, timeout
precedence, or repository-drift rejection.

## Fail-first Tests

| Test | Contract |
| --- | --- |
| `TC-0202` | a current exact-goal packet emitted with an explicit ancestor base routes to the exact Evidence-bound `close_goal` action without mutation |
| `TC-0203` | an unresolvable recapture or content drift fails closed to the existing `emit_completion_packet` action |

The RED test must fail on the current implementation by returning
`emit_completion_packet`, then pass from the one routing correction.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_goal_close_routing.py
PYTHONPATH=src pytest
PYTHONPATH=src ruff check .
PYTHONPATH=src python -m pcl validate --strict --json
PYTHONPATH=src python -m pcl render --json
```

Real-project dogfood must reproduce the `E-0686` non-HEAD base shape with
short deterministic checks, prove pre-fix duplicate-finish routing and
post-fix exact close routing, and preserve read-only event/DB checksums across
`next`.

The v0.5.5 wheel/sdist and clean-wheel smoke are rebuilt after this correction.

## Result

The shared close-routing service now recaptures repository identity from the
validated `repository.base_revision` recorded by the newest exact-goal packet.
Invalid packet shape and a base that cannot be resolved both return the
existing `emit_completion_packet` fallback without mutation.

Fail-first, targeted and full regression, source dogfood, isolated installed
wheel dogfood, artifact construction, strict validation, audit, and render
results are recorded in
`docs/evidence/0214-non-head-goal-packet-routing-validation.md`.

## Stop conditions

Stop and request a separate decision before:

- database migration or dependency addition;
- packet v2 or a public JSON field/exit-semantics change;
- relaxed health, risk, target, timeout, latest-only, or drift checks;
- automatic Goal closure;
- push, tag, GitHub Release, PyPI/TestPyPI, pipx, announcement, or other public
  mutation.
