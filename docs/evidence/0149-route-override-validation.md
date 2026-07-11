# 0149 Route Override Validation Evidence

- Date: 2026-07-11
- Project Loop target: G-0018 / T-0035
- Feature / Story / Test: F-0019 / US-0017 / TC-0036

## Implemented contract

- Packaged `route-override/v1` schema, validator, and contract CLI support.
- Zero-mutation `pcl route override --dry-run` preview.
- Explicit override requires actor, reason, target, and effective profile.
- Original recommendation and policy resolution are separate immutable,
  hash-bound Evidence artifacts.
- One apply transaction writes three Evidence rows/links and one aggregate
  event/outbox pair; exact repeats are idempotent.
- Permission, migration, destructive-operation, human-review, and R4 route
  floors fail closed on downgrade.
- Policy risk floors are reapplied to the effective profile.
- `pcl route current` verifies referenced artifact hashes before returning the
  original/effective view.
- Optional `adaptive-route-context/v1` metadata flows through task context and
  completion packets; resume handoff context refs include the override and
  original artifacts.
- DB schema remains 8; no runtime dependency was added.

## Commands and results

```text
ruff check .
All checks passed!

pytest -q tests/test_baseline_fixtures.py tests/test_route_overrides.py tests/test_completion_packet_contract.py tests/test_finish.py tests/test_context.py tests/test_resume.py
124 passed in 19.39s

git diff --check
exit 0

pytest -q
813 passed, 1 skipped in 114.88s
```

The CLI help snapshot was regenerated mechanically for `route override` and
`route current`.

## Residual human gate

US-0017 remains draft. TC-0036 and F-0019 must not be marked terminal until a
human approves or waives the Story. Route-quality conclusions also remain for
the 0149a human dogfood review.
