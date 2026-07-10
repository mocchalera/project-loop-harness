# Crash and concurrency reliability suite

The required CI suite includes `tests/test_crash_concurrency.py`. It uses an
abrupt subprocess exit at explicit fault points and process barriers or advisory
locks for races; test correctness does not depend on timing sleeps.

## Fault and recovery matrix

| Fault point | Expected durable state | Audit classification | Recovery exercised |
|---|---|---|---|
| before SQLite commit | old domain/event/outbox and JSONL | clean | safe command retry |
| after commit, before projector | committed event and pending outbox | repairable | `audit repair --apply` |
| projector after attempt starts | committed event and pending outbox | repairable | idempotent projection retry |
| before JSONL append | committed event and pending outbox | repairable | `audit repair --apply` |
| during JSONL append | partial trailing line and pending outbox | unsupported/review-required | backup and `rebuild-jsonl --apply` |
| after JSONL write, before fsync | complete or partial tail after abrupt exit | repairable when complete; review-required if partial | projection retry or reviewed rebuild |
| after fsync, before delivered commit | canonical JSONL line and pending outbox | repairable | match without duplicate append |
| after delivered commit | matching SQLite/outbox/JSONL | clean | no-op |
| between migration statements | pre-migration schema | unsupported by new audit contract until migration | atomic migration retry |
| before Evidence temp write | no artifact or metadata | clean | safe command retry |
| after Evidence temp write | unreferenced temp | human review | explicit quarantine; no silent delete |
| after Evidence rename, before commit | unreferenced final manifest | human review | explicit quarantine; no silent delete |

The process hook requires both `PCL_ENABLE_TEST_FAULTS=1` and an exact
`PCL_TEST_FAULT_POINT`. Production execution does not set either. An optional
`PCL_TEST_FAULT_MARKER` records the PID and reached point immediately before
termination so a CI failure identifies the boundary reached.

## Concurrency and platform coverage

The fast required suite runs two rounds of eight writer processes, an exclusive
migration-lock/writer case, simultaneous projector/mutation start, and a bounded
SQLite busy-timeout case. It checks contiguous sequence allocation, unique event
IDs, domain row counts, JSONL logical counts, and `PRAGMA foreign_key_check`.

ENOSPC and EACCES are injected as concrete OS errors because real disk exhaustion
is unsafe in shared CI and chmod-based permission tests are unreliable for root
and Windows runners. The suite is required on Linux and is also runnable on
macOS. The current runtime requires `fcntl`, so Windows cannot initialize a
project and is outside the supported crash/concurrency subset. The fault helper
uses `os._exit(137)` instead of SIGKILL if a future Windows lock implementation
makes that runtime path available.

The suite remains part of default `pytest`. A larger nightly stress tier is not
currently justified; add a `reliability_stress` marker only if measured CI time
exceeds the repository's few-minute target. CI uploads per-fault audit/validate
summaries plus stress counts and timing from `reliability-artifacts/`.
