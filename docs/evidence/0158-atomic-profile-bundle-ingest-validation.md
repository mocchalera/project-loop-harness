# 0158 Atomic Profile bundle ingest validation

**Date:** 2026-07-12

**SQLite schema:** 8, unchanged

**Runtime dependencies:** unchanged

## Delivered

- Real `pcl profile ingest` re-runs the complete source validation, copies only
  listed files to a unique staging directory, and re-validates request,
  bundle, artifact bytes, contracts, and cross-references from staging.
- An fsynced Evidence manifest records profile/request/bundle metadata, logical
  and stored artifact paths, sizes, and hashes. The staging directory is
  atomically renamed before one SQLite transaction inserts exactly one
  `profile_output_bundle` Evidence, one target link, one
  `profile_output_ingested` event, and its outbox record.
- Exact replay returns the original Evidence/event IDs with zero mutation.
  Same-ID/different-digest replay fails closed.
- `failed` requires `--accept-failed` and a non-empty human summary.
  `needs_human` remains blocked for task 0159 Decision support.
- Stored control files and artifacts are hash/size reconciled by audit. Audit
  also reports unreferenced staging and finalized directories without deleting
  or inferring durable state.

## Fault and mutation verification

Four subprocess SIGKILL fault points cover:

- after copy;
- immediately before rename;
- after rename and before commit;
- after event/outbox insertion and before commit.

Every crash leaves SQLite counts and `events.jsonl` unchanged. Audit reports
the surviving staging/finalized directory with `quarantine_or_report`
guidance. Normal rejected paths clean staging and final destinations.

## Verification

```text
$ ruff check .
All checks passed!

$ PYTHONPATH=src pytest -q tests/test_profile_ingest_dry_run.py tests/test_distribution.py
46 passed

$ PYTHONPATH=src pytest -q
922 passed, 1 skipped
```

Wheel and sdist checks confirm the atomic ingest service, CLI flags, contracts,
built-in manifest, and ingest tests are included without a migration or new
dependency.
