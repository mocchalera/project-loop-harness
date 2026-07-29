# P0-B terminal readiness guard fail-first evidence

- Date: 2026-07-30
- Base commit: `c923a1eb5ef6360896c72dfa00570798cc8c9c21`
- Branch: `codex/plh-mutation-tail-p0a-20260730`
- Schema migration: none
- Dependency addition: none

## Command

```text
PYTHONPATH=src pytest -q tests/test_task_terminal_guard.py
```

## Result

```text
FF.FF
4 failed, 1 passed in 1.12s
```

The four expected failures proved the missing P0-B behavior:

1. A Task linked to a merely `passing` Feature committed `done`, appended the
   Task event/outbox/JSONL record, ran the P0-A tail, and rewrote dashboard
   artifacts instead of returning `task_terminal_readiness_failed`.
2. A Task with an incomplete dependency committed the same unsafe transition
   instead of preserving the complete pre-call mutation/artifact snapshot.
3. Two serialized concurrent `done` requests still produced one mutation, but
   the successful result and event lacked the required identical readiness
   receipt.
4. Text mode exited zero and wrote a success line to stdout instead of exiting
   one with ordered readiness diagnostics on stderr.

The passing characterization fixed the existing same-state contract: an
already-`done` Task returned `changed=false` without a new event, render, or
preflight even after a later dependency made current readiness blocking.
