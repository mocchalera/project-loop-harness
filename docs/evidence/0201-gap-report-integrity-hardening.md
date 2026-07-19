# 0201 Gap Report Integrity Hardening Evidence

Date: 2026-07-19

## Review findings closed

1. Gap Report artifacts are created through canonical directory descriptors;
   directory, temporary-file, and final-file symlinks fail before any external
   write or PLH mutation.
2. `candidate_lessons` is an object keyed by `lesson_id`, duplicate raw JSON
   keys fail during loading, and the packaged timestamp pattern accepts only
   real UTC dates at second precision.
3. The anchor hash covers the exact stored UTF-8 bytes, so same-size,
   whitespace-only drift is detected.
4. Class filtering uses the immutable anchor value and exposes separate
   `recorded_gap_class` and `artifact_gap_class` fields.

## Verification

- `PYTHONPATH=src pytest -q tests/test_gap_reports.py`
  - passed: 27
- `PYTHONPATH=src pytest -q tests/test_gap_reports.py tests/test_contract_cli.py tests/test_evidence_add.py tests/test_evidence_show.py tests/test_evidence_sets.py tests/test_cli_init.py tests/test_distribution.py`
  - passed: 128
- `PYTHONPATH=src pytest -q`
  - passed: 1160
  - skipped: 1
- `ruff check .`
  - passed
- `python -m build --outdir /tmp/pcl-gap-0201-dist.JtvmwW`
  - built wheel and sdist successfully
  - emitted pre-existing setuptools license-metadata deprecation warnings
- `python scripts/verify_sdist_contracts.py --dist-dir /tmp/pcl-gap-0201-dist.JtvmwW`
  - passed; unpacked-sdist contract test: 1 passed
- isolated wheel install at `/tmp/pcl-gap-0201-wheel.vvioRV`
  - `pcl --help`: passed
  - `pcl contract validate --type gap-report/v1 tests/fixtures/gap_report/minimal.json --json`: `ok: true`

No dependency, migration, hosted service, external publication, or automatic
durable-owner write was added.
