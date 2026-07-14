# CI portability repair verification

Date: 2026-07-15 JST

## Failure evidence

GitHub Actions run
[29346501646](https://github.com/mocchalera/project-loop-harness/actions/runs/29346501646)
failed in every Python 3.10-3.13 test job with the same two failures:

- `tests/test_distribution.py::test_sdist_contains_profile_contracts_and_builtin_manifest`
  invoked `python -m build`, but the `dev` extra installed by CI did not provide
  the `build` frontend.
- `tests/test_skill_usage_report.py::test_skill_usage_report_source_health_window_and_invalid_json`
  expected one malformed relevant JSONL line, but the standard-library scan used
  when `rg` is unavailable did not select that line.

The v0.5.0 adoption demo tests passed in the failing CI run.

## Repair

- Added `build>=1` to the `dev` extra because the test suite directly invokes
  the module.
- Added the project-control-loop skill path to the standard-library Codex JSONL
  selection needles.
- Forced the affected test through the no-`rg` path so the behavior no longer
  depends on the developer machine.
- Added an assertion that the distribution-test prerequisite remains in the
  `dev` extra.

## Local verification

```text
ruff check src/pcl/skill_usage_report.py tests/test_distribution.py tests/test_skill_usage_report.py
All checks passed!

PYTHONPATH=src python -m pytest -q tests/test_distribution.py tests/test_skill_usage_report.py
19 passed in 9.64s

PYTHONPATH=src python -m pytest -q
1001 passed, 1 skipped in 190.43s
```

Remote verification is complete only after the pushed GitHub Actions matrix is
green on Python 3.10, 3.11, 3.12, and 3.13.
