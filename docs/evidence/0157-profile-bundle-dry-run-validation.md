# 0157 Profile bundle dry-run validation

**Date:** 2026-07-12

**SQLite schema:** 8, unchanged

**Provider or verification command execution:** none

## Delivered

- `pcl profile ingest --request ... --bundle ... --dry-run` validates the
  frozen request and output-bundle contracts and returns a deterministic
  `profile-ingest-plan/v1` mutation plan.
- Request binding covers current project fingerprint, target, built-in Profile
  manifest, Work Brief Evidence, route Evidence, and authorization presence.
- Bundle validation is fail-closed for digest/status, required roles, listed
  paths, symlink components, case-fold collisions, declared/actual size, byte
  hash, artifact contracts, and Council cross-references.
- Request and bundle manifest size caps are checked before JSON parsing;
  declared aggregate artifact bytes are checked before artifact reads/hashes.
- Only manifest-listed files are inspected. Neighboring files are ignored.
- Proposed verification commands remain inert data. A test command that would
  create a sentinel file is never executed.
- `partial`, `budget_exhausted`, and `failed` plans always expose
  `safe_to_run: false`; failed bundles require an explicit future acceptance
  flag and plan zero mutations.

## Verification

```text
$ ruff check .
All checks passed!

$ PYTHONPATH=src pytest -q tests/test_profile_ingest_dry_run.py
32 passed

$ PYTHONPATH=src pytest -q
912 passed, 1 skipped

$ PYTHONPATH=src python -m pcl profile ingest --help
usage: pcl profile ingest [-h] --request REQUEST_FILE --bundle BUNDLE_FILE
                          --dry-run
```

Every successful and rejected dry-run compares SQLite row counts, JSONL,
Evidence, reports, dashboard, and exports before and after the command.
