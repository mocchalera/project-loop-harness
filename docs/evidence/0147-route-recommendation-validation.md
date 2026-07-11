# 0147 Route Recommendation Validation Evidence

- Date: 2026-07-11
- Project Loop target: G-0018 / T-0035
- Feature / Story / Test: F-0017 / US-0015 / TC-0034

## Implemented contract

- Packaged `route-recommendation/v1` schema and validator.
- Read-only `pcl route recommend --target ...` default.
- Explicit idempotent `--record` Evidence/event/outbox path.
- Stable Direct/Discover/Assure ordered rules and reason codes.
- Case-folded POSIX/Windows path normalization.
- Input digest covers target, policy version, signals, and Work Brief content.
- Model self-assessment is never used as a risk-lowering signal.

## Commands and results

```text
pytest -q tests/test_route_recommendation.py tests/test_work_briefs.py tests/test_contract_cli.py
23 passed in 0.98s

pytest -q tests/test_route_recommendation.py tests/test_work_briefs.py tests/test_contract_cli.py tests/test_baseline_fixtures.py
25 passed in 4.33s

ruff check .
All checks passed!

pytest -q
exit 0; one existing skip

pytest --collect-only -q
798 tests collected in 0.11s

git diff --check
exit 0
```

The CLI help snapshot was regenerated mechanically. Only `pcl-help.json`
changed, adding the `route` command.

## Residual human gate

US-0015 remains draft. TC-0034 and F-0017 must not be marked terminal until a
human approves or waives the Story.
