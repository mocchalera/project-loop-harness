# 0177 Advisory checkpoint routing evidence

## Outcome

- Default checkpoint mode is `advisory` with `feature_interval: 5`.
- Advisory checkpoints remain visible in `pcl checkpoint status` and the
  dashboard risk summary without replacing normal Task or Goal routing.
- `mode: blocking` preserves the former human-gated `checkpoint_review` route.
- `mode: off` suppresses cadence recommendations.
- Invalid mode and interval values produce typed errors and validation findings.
- No database migration or dependency was added.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_dashboard_data_contract.py tests/test_checkpoints.py tests/test_next_actions.py tests/test_dashboard.py
50 passed in 10.35s

ruff check .
All checks passed!

PYTHONPATH=src pytest -q
1011 passed, 1 skipped in 217.99s
```

## Fresh-project smoke

A fresh temporary project initialized from the bundled template produced:

```yaml
checkpoint:
  mode: advisory
  feature_interval: 5
```

The smoke then passed:

```text
pcl checkpoint status --json
mode=advisory, threshold=5, checkpoint_requires_human=false

pcl validate --strict --json
ok=true, errors=0, warnings=0

pcl render --json
dashboard HTML and dashboard-data.json generated
```

The normal non-strict doctor reported only expected untouched-template advice
for `project.name`, empty project commands, and missing finish checks.

## Regression repaired during verification

The first full-suite run found one exact-shape `dashboard-data/v1` contract
test that did not yet include the additive `checkpoint` field. The contract
documentation and shape test were updated, after which the full suite passed.
