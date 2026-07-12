# 0156 Profile read-only preparation validation

**Date:** 2026-07-12  
**SQLite schema:** 8, unchanged  
**Provider execution:** none

## Delivered

- `pcl profile prepare council.discovery --target task:T-XXXX` builds a
  validated `profile-run-request/v1` without executing a runner.
- A healthy unapproved Brief is allowed for Discovery and explicitly labelled;
  ambiguous candidates require `--brief`.
- Route recommendation Evidence is mandatory, hash-checked, and recomputed for
  freshness. Missing, stale, tampered, direct-route mismatch, and audited
  override paths have stable diagnostics and repair guidance.
- Project fingerprint binds the absolute local root only inside its digest;
  request output exposes only basename and digest.
- Context is adapted from machine context, with no dashboard HTML, database,
  local root, `.env` sentinel, or transcript.
- Different wall-clock times produce the same request ID and basis digest when
  semantic state is unchanged.
- Default data policy is offline/non-paid with `authorization: null`.
- `--output` writes only the named JSON file.

## Verification

```text
$ ruff check .
All checks passed!

$ pytest -q tests/test_profile_prepare.py
6 passed

$ pytest -q
880 passed, 1 skipped
```

Read-only tests hash database row counts, JSONL, Evidence, reports, dashboard,
and exports before and after successful and rejected preparation.

