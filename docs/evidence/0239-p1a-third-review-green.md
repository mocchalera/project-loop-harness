# P1-A third independent review remediation GREEN

## Source authority

- Source commit:
  `eaa514c15df84be81254f737b37825baf6d06203`
- Schema: 8
- Runtime dependencies: 0
- P1-B/P1-C changes: none
- Linux host E2E: not executed on this Darwin host
- Portable production Git route: verified through `pass_fds` plus `fchdir`

## Implemented closure

1. `connect_read_only` builds its SQLite URI from the already-absolute retained
   path and performs no second symlink/path resolution.
2. Direct tails use `safe_to_retry_original: false` for complete, not-changed,
   and partial results. Partial and unexpected tail failures exit 6.
   `mutation_committed` remains true for a changed request and false for an
   idempotent `changed=false` tail failure.
3. `direct-tail-recovery/v1` is command-null and binds an exact Task validation
   operation to the retained root device/inode. It contains no original
   pathname authority.
4. Exclusive renderer capabilities are module-issued and live-registry-backed.
   Validation checks root, loop directory, held FD, current lock-file inode,
   issuing PID/thread, active owner, and exclusive mode.
5. The real-process root ABA attack is rejected while a same-root rename and
   the normal Direct no-reentry route continue to work.

## Exact verification

Initial fail-first:

```text
12 failed, 2 passed in 3.20s
```

Final review-specific attack set:

```text
19 passed in 5.18s
```

Focused:

```text
277 passed, 1 skipped in 39.87s
```

Full:

```text
1399 passed, 2 skipped in 401.52s (0:06:41)
```

Static and compatibility checks:

```text
PYTHONPATH=src python -m ruff check .
All checks passed!

PYTHONPATH=src python -m pytest -q -rs tests/mcp/test_external_conformance.py
8 passed, 1 skipped in 0.97s

PYTHONPATH=src python -m pcl --help
exit 0

PYTHONPATH=src python -m pcl start --help
exit 0

git diff --check
exit 0
```

The MCP skip is the optional official SDK (`mcp==1.28.1`), which was not added.
The full-suite skips are that optional SDK path and the Linux-only Direct Git
E2E. The portable production POSIX Git regression passed.

## Fresh Git smoke

- Root: `/tmp/pcl-p1a-third-smoke.LuzLni`
- Git HEAD / stored initial revision:
  `2bf82c14ba3ef9a6b107ae67cae7e635dd184d90`
- First request: exit 0, `started`, `mutated: true`
- Exact retry: exit 0, `already_started`, `mutated: false`
- Changed input: exit 1, `direct_setup_idempotency_conflict`
- Doctor: exit 0 with the expected fresh-template warnings
- Strict validate: exit 0, active findings 0
- Audit: clean, DB/JSONL/outbox `17/17/17`, pending 0
- Render: exit 0

## Current project health

- `pcl doctor --strict --json`: exit 0, active findings 0
- `pcl validate --strict --json`: exit 0, active findings 0
- Task-scoped audit for `T-0003` since `EV-E71D510409F1`: exit 0,
  anomalies 0, unanchored 0
- Root audit: exit 6 only for the known superseded historical source drift in
  `E-0013` and `E-0014`; current Evidence corruption 0 and pending outbox 0
- Skill4 SHA-256:
  `65f4c904b4f8891c70ea16ee18e2a016dea35b323723c0b3143b6639a246b5d1`

## Residual boundary

No Linux machine was available for this run. The Linux-only production E2E is
present but skipped on Darwin; this proof does not claim a live Linux result.
The renderer still makes no two-file/process-crash atomicity claim.
