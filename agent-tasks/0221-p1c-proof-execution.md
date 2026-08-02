# 0221: P1-C C3 proof execution

- **Status:** Implemented locally; persistence/anchoring and C4 not authorized
- **Milestone:** P1-C C3 deterministic proof execution
- **Priority:** P1
- **Dependency:** C2 accepted implementation at
  `c4064e5b48ff877646eef06e1e835353f12f3288`
- **Schema/dependencies:** schema 8; migration 0; runtime dependency 0
- **PCL state effect:** 0; no event, Evidence, outbox, database, render, or
  lifecycle mutation

## Authorized C3 contract

Consume C2's frozen `PreparedCheck` as the sole spawn vector. Revalidate the
resolved executable and fresh canonical source/C1/diff authority, apply the
final C2 seal immediately before spawn, and execute serially in a bounded POSIX
process-group controller. Return strict canonical in-memory packets,
checkpoints, committed-or-withheld stream logs, receipts, results, aggregate,
and bundle manifest. `reuse_authorized` remains false.

Capture Feature-linked current proof in separate read-only SQLite snapshots.
A standalone Task is not applicable. Unrelated HWM movement is excluded from
the digest; relevant Evidence/link/event/content drift is withheld. Aggregate
`current_proof.proof_sha256` is `sha256 | null`, with null restricted to
indeterminate observations.

## Exclusions

No public CLI, persistence or anchoring, Evidence/event/outbox/database write,
dashboard/render, terminal/lifecycle mutation, schema migration, dependency,
C4 semantic role/canary evaluation, retained-root sweep, or reuse approval.
Existing `db.py`, `authority_surface.py`, `evidence.py`, and `tasks.py` behavior
is unchanged.

## Verification boundary

Use source-tree execution and disable caches:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_proof_execution_contract.py tests/test_proof_execution.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_proof_workspace.py tests/test_authority_surface.py tests/test_verification_manifest.py tests/test_finish_workspace.py
ruff check --no-cache .
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider
```

The adversarial matrix covers all verdicts and precedence, exact prefix/suffix,
candidate-only execution, source/clone/tool/pre-spawn drift, ENOENT/EACCES,
TERM/KILL/descendant/EPERM behavior, exact caps and binary dual streams, secret
withholding and false positives, current-proof digest domains and read-only
effects, same-workspace idempotency, and the no-CLI/no-persistence boundary.

See [proof-execution-v1.md](../docs/proof-execution-v1.md).
