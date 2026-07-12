# 0155 Profile contract runtime and registry validation

**Date:** 2026-07-12  
**SQLite schema:** 8, unchanged  
**Runtime dependency delta:** none

## Delivered

- Seven packaged Draft 2020-12 schemas and one standard-library validator
  module per Profile contract.
- Strict JSON loading rejects duplicate keys and non-finite numbers.
- Contract-specific checks cover canonical digests, duplicate IDs,
  cross-references, normalized/case-folded paths, authorization basis,
  mediated human provenance, provider/cost/data-class scope, and runner
  non-execution.
- Built-in-only `council.discovery` registry with deterministic
  `pcl profile list/show/validate` JSON and text surfaces.
- Public help distinguishes `runner_profile_id`, `route_profile`, and
  `role_profile`.
- Wheel and sdist include all schemas and the data-only manifest. Clean-wheel
  smoke runs all three Profile commands without source checkout, network, or
  provider credentials.

## Verification

```text
$ ruff check .
All checks passed!

$ pytest -q
874 passed, 1 skipped

$ pytest -q tests/test_profile_contracts.py
28 passed

$ pytest -q +    tests/test_distribution.py::test_sdist_contains_profile_contracts_and_builtin_manifest +    tests/test_distribution.py::test_wheel_install_smoke_runs_cli_mcp_and_bundled_templates
2 passed

$ pytest -q tests/test_baseline_fixtures.py
2 passed
```

The read-only CLI tests use an empty uninitialized directory and assert zero
files are created. The distribution smoke removes `PYTHONPATH`, installs the
built wheel into a fresh virtual environment, and executes Profile commands
from outside the source checkout.

