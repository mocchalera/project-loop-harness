# P0-B finish race/freshness review RED evidence

Date: 2026-07-30

Base:
`5ae1a8068d0bfaa1d0ead8c36b4f79ecf1133305`

Independent re-review:
`c12dd3d9`

## Fail-first command

```text
PYTHONPATH=src pytest -q \
  tests/test_finish.py::test_finish_prioritizes_evidence_set_drift_over_repository_race
```

Result before the production fix:

```text
1 failed in 1.18s
```

The permanent test creates a current, completion-policy-approved Evidence Set,
then coherently rewrites its artifact and copies the bound reports to a new
ordinary `work/` path while finish checks run. This changes both the strict
Task proof digest and the repository snapshot.

The command returned exit 1 but no typed error, so the assertion failed with:

```text
KeyError: 'error'
```

The returned finish result had `race_detected=true`,
`INCOMPLETE_VALIDATION`, and `strict_evidence_set_hash_mismatch`, but still
recorded completion-check Evidence and an incomplete packet event/outbox,
JSONL line, packet Evidence, and packet file. The Task remained `in_progress`
and the dashboard was unchanged. This proves that repository-race
classification disabled the final Task freshness rollback.

No production source change was present when this RED result was captured.
