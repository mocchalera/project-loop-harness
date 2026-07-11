# 0148 Adaptive Policy Validation Evidence

- Date: 2026-07-11
- Project Loop target: G-0018 / T-0035
- Feature / Story / Test: F-0018 / US-0016 / TC-0035

## Implemented contract

- Packaged strict `adaptive-policy/v1` default policy and resolution schema.
- Read-only `pcl policy resolve` and `pcl policy explain` commands.
- Deterministic precedence: defaults, profile, matched project rules, risk floor.
- Per-axis source attribution and matched-rule reporting.
- Conflicting matched rules fail closed.
- R3/R4 verification and checkpoint floors cannot be weakened by custom policy.
- No schema migration or dependency addition.

## Commands and results

```text
ruff check .
All checks passed!

pytest -q tests/test_adaptive_policy.py tests/test_route_recommendation.py tests/test_work_briefs.py tests/test_baseline_fixtures.py
26 passed in 4.40s

pytest -q
805 passed, 1 skipped in 112.58s
```

The CLI help snapshot was regenerated mechanically to add the read-only
`policy resolve` and `policy explain` command group.

## Residual human gate

US-0016 remains draft. TC-0035 and F-0018 must not be marked terminal until a
human approves or waives the Story.
