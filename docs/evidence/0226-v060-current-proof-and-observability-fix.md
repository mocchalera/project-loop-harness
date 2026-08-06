# 0226 v0.6.0 current-proof and observability fix

**Recorded:** 2026-08-06

**Worktree:** `codex/plh-mutation-tail-p0a-20260730`  
**Pre-proof HEAD:** `f19f36bf4e6bc5d19ee8f7391c2a085e1b427868`

## Gate 1 — current-proof (single 600s run, retry0)

Command:

```bash
PYTHONPATH=src python -m pcl finish --emit-packet --goal G-0005 --timeout 600 --json
```

Result:

| Field | Value |
| --- | --- |
| Finish `ok` | `true` (command completed; checks not all green) |
| Finish `exit_code` | `1` |
| Packet outcome | `INCOMPLETE_VALIDATION` |
| Packet evidence | `E-0078` |
| Packet path | `.project-loop/evidence/completion-packets/ccf94fd54ec27b5c1de8bec4eda801f2b0ea422af0ef7c9f29219486fccf93b2.json` |
| Lint check | `ruff check .` **passed** (`E-0074`, ~0.13s) |
| Test check | `pytest` **failed** (`E-0076`, ~407s, not timed out) |

Failure signature (from `E-0076` stdout/stderr):

- Suite progressed through `tests/test_locks.py`.
- Live finish injects `-p pcl.runner_observability`.
- `tests/test_locks.py::test_windows_contention_times_out_with_structured_error` monkeypatches `locks.time.monotonic` with an exhaustible iterator.
- `_PytestEventSink.emit` called `time.monotonic()` for `elapsed_seconds` and raised `StopIteration`.
- Pytest raised `INTERNALERROR` and aborted the session mid-file.

This was **not** a timeout. Per operator instruction, the single finish run was not retried.

Prior historical incomplete packet for the same goal: `E-0073` (2026-08-05, also `INCOMPLETE_VALIDATION`).

## Gate 2 — audit / validate / render (post-proof)

| Command | Result |
| --- | --- |
| `pcl doctor --json` | `ok: true`, zero findings |
| `pcl validate --strict --json` | `ok: true`, zero active/historical findings |
| `pcl render --json` | `ok: true` |
| `pcl audit check --summary --json` | `ok: false`, `status: issues_found`, **2 historical** `human_review` / `evidence_metadata_file_mismatch` on `task:T-0002` (pre-existing; not introduced by this gate) |

## Post-proof fix (not a second finish run)

Root cause fix in `src/pcl/runner_observability.py`:

- Bind the real clock once as `_MONOTONIC = time.monotonic` at import.
- Use `_MONOTONIC()` in parent `RunnerObservabilityRecorder` and child `_PytestEventSink`.
- Prevents suite monkeypatches of `time.monotonic` from crashing the injected finish observer.

Regression tests in `tests/test_runner_observability.py`:

- `test_observer_survives_suite_monkeypatch_of_time_monotonic`
- `test_parent_recorder_uses_bound_monotonic_under_time_monkeypatch`

Targeted acceptance subset (operator gate; full suite not re-run):

```bash
PYTHONPATH=src python -m pytest \
  tests/test_runner_observability.py \
  tests/test_locks.py \
  tests/test_finish.py \
  tests/test_goal_close_routing.py \
  tests/test_runner_authority.py \
  tests/test_guarded_process.py -q
```

Result: **120 passed** in ~64s.

## Release boundary

- Goal `G-0005` remains **open**. Packet `E-0078` is not `COMPLETED_VERIFIED` / `COMPLETED_WITH_RISK`, so `pcl goal close` is not authorized by terminal policy.
- No annotated tag, push, GitHub Release, or PyPI upload was performed.
- A **second** `pcl finish --emit-packet` re-proof is required after the observability fix lands before local publication can claim green current-proof.

## Residual gates

1. Re-run current-proof once after the fix lands (operator must authorize a new finish attempt; retry0 for the failed attempt is exhausted).
2. Close `G-0005` only with a green completion packet Evidence ID.
3. Local RC documentation / SECURITY line bump / packaging smoke as in `docs/release-checklist.md`.
4. Remote publication (push/tag/GitHub/PyPI) remains a separate authorized step even after local RC.
