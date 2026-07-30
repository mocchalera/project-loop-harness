# P0-B strict current-proof review GREEN evidence

Date: 2026-07-30

Review base:
`7de0c7c49065cffba8ff45ef50d8cdd02e802c0a`

Remediation implementation:
`f4aae0d`

Independent review:
`1230d59b`

## RED to GREEN

The five fail-first regressions at the review base produced:

```text
5 failed in 3.26s
```

They reproduced coherent copied-Evidence and Evidence Set substitution through
direct Task done and finish, an unchanged HWM/digest after event-free proof
substitution, and duplicate blocked/risk classification for an unrelated
standalone Evidence warning.

After remediation, the same five tests produced:

```text
5 passed in 1.96s
```

## Corrected contract

- Public strict copied-Evidence and Evidence Set resolvers now delegate to the
  same implementation used with a caller-owned SQLite snapshot.
- Every copied Evidence or Evidence Set in the current proof closure is
  strictly resolved inside Task read/list/next, direct done's existing
  `BEGIN IMMEDIATE`, and finish's final `BEGIN IMMEDIATE`.
- The canonical input binds strict health, recording event ID/sequence,
  manifest/artifact bytes SHA, canonical artifact SHA, and member/report hashes.
  A coherent rewrite without an event changes the digest even when the event
  HWM is unchanged.
- Strict current-proof findings are blocked before direct mutation or finish
  completion-check Evidence/packet files. The direct and finish regressions
  compare Task/event/outbox/JSONL/dashboard bytes and terminal packet/check
  artifacts to prove zero mutation.
- Manual Evidence assessment is retained only for unhealthy superseded history.
  Active unrelated warnings use formal validation projection, remain one risk,
  and do not create a standalone Evidence prerequisite. Current-proof warnings
  and global active error/unknown/human-required findings remain blockers.

## Verification

```text
Focused strict Evidence/Set/Task/finish:
133 passed in 39.32s

Focused terminal/validation/lifecycle/next/mutation-tail/CLI/baseline/Skill:
355 passed in 73.43s (0:01:13)

PYTHONPATH=src pytest -q
1320 passed, 1 skipped in 451.57s (0:07:31)

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
passed

PYTHONPATH=src python -m pcl --help
exit 0
```

The four loaded/distributed `project-control-loop` Skill copies are
byte-identical at SHA-256
`46dbb9640da5a6d256ab63aba0bb3bcdf9074f8305667c49adaf9b229008a30c`.

## Preserved boundaries

No schema migration, dependency, telemetry, force/override, lite/config bypass,
human-approval fabrication, Evidence/completion-policy weakening, push,
main-checkout change, Task completion/removal, or external operation was
introduced.

Story `US-0002` remains draft, Tests `TC-0014`–`TC-0018` remain planned, and
Task `T-0002` remains `in_progress`. The review's two deferred Low findings
(Task-list N+1 and baseline normalizer event-ID equivalence) and the existing
P0-A Low three remain explicitly out of this remediation.
