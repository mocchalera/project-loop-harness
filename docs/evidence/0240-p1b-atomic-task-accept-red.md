# P1-B Atomic Task Accept fail-first RED

## Authority and base

- base HEAD: `185a03ed8ddb999ccf354da2d4f86f36119aee7c`
- branch: `codex/plh-mutation-tail-p0a-20260730`
- schema: `8`
- runtime dependency or migration changes: none
- immutable final design: task `7aad46ce`, latest raw report `seq37`, composed with the selected V8 authority and final index
- independent final design review: task `1069b352`, report `seq1`, High 0 / Medium 0 / Low 0
- P0-B final review: task `c12dd3d9`, report `seq2`

## PCL behavior tracking

- Task `T-0004`
- Feature `F-0004`
- draft Story `US-0005` (the implementation instruction was not treated as semantic Story approval)
- planned Tests `TC-0025` through `TC-0028`
- `pcl validate --strict --json`: `ok=true`, active findings 0, historical findings 0
- `pcl render --json`: success

## Fail-first commands and expected failures

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -p no:cacheprovider --basetemp=/tmp/pcl-p1b-red-prefixed tests/test_prefixed_ids.py -q
```

Result: collection error because `pcl.prefixed_ids` does not exist.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -p no:cacheprovider --basetemp=/tmp/pcl-p1b-red-core tests/test_task_accept.py -q
```

Result: `6 failed`; every case reaches the intended missing fixed CLI surface and argparse rejects `task accept`.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -p no:cacheprovider --basetemp=/tmp/pcl-p1b-red-recovery tests/test_task_accept_recovery.py -q
```

Result: collection error because `pcl.task_accept` does not exist.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -p no:cacheprovider --basetemp=/tmp/pcl-p1b-red-contracts tests/test_task_accept_contracts.py -q
```

Result: collection error because startup mode `APPROVAL_TASK_ACCEPT_WRITE` does not exist.

These failures are contract failures at the new P1-B surface, not failures in an existing legacy command.
