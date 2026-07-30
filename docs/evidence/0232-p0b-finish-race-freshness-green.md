# P0-B finish race/freshness remediation GREEN evidence

Date: 2026-07-30

Review base:
`5ae1a8068d0bfaa1d0ead8c36b4f79ecf1133305`

Remediation implementation:
`145ce35f9a5026fedad78cdfbacc00f468831d7d`

Independent re-review:
`c12dd3d9`

This Evidence supersedes `E-0014`. That earlier Green Evidence correctly
covered strict current-proof identity and standalone warning classification,
but missed the overlap between strict Evidence Set drift and repository-race,
failed-check, or input-effect classification.

## RED to GREEN

At the review base, the permanent Evidence Set/repository-race regression
failed before any production source change:

```text
PYTHONPATH=src pytest -q \
  tests/test_finish.py::test_finish_prioritizes_evidence_set_drift_over_repository_race

1 failed in 1.18s
```

Finish returned ordinary `INCOMPLETE_VALIDATION` with `race_detected=true`
instead of typed `finish_target_readiness_changed`. It left one terminal event
and outbox record, one JSONL line, completion-check Evidence, packet Evidence,
and a packet file, although the Task stayed `in_progress`.

After remediation, permanent regressions cover the repository-race,
failed-check, and input-effect branches:

```text
3 passed in 3.23s
```

Each branch returns typed `finish_target_readiness_changed` before storing
completion-check Evidence, finish-attempt Evidence/file, packet Evidence/file,
or terminal events. The tests compare Task/event/outbox/JSONL/dashboard bytes
and all three terminal artifact directories. Snapshot-stable failed checks,
repository races, and input mutation retain their existing incomplete
attempt/packet semantics.

## Corrected contract

- A Task pre-check receipt with `terminal_allowed=true` unconditionally
  requires a fresh Task/HWM/canonical strict-proof comparison in the final
  `BEGIN IMMEDIATE`.
- Check result, repository-race state, and input-effect classification cannot
  disable freshness enforcement. When drift overlaps another failure,
  freshness takes precedence.
- Both completion-packet and finish-attempt paths use the same exact Task
  resolver and `task_terminal_readiness_for_row` snapshot evaluation before
  `_store_check_evidence`.
- Direct Task done, strict Evidence and Evidence Set resolution, standalone
  warning behavior, current/global/Feature/human/Goal guards, same-state and
  concurrent Task behavior, and P0-A post-commit mutation-tail behavior are
  unchanged.

## Verification

```text
Finish suite:
45 passed in 53.15s

Strict Evidence/Set/Task/next:
138 passed in 45.91s

Validation/lifecycle/mutation-tail/CLI/baseline/Skill:
163 passed in 49.69s

PYTHONPATH=src pytest -q
1323 passed, 1 skipped in 309.08s (0:05:09)

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
passed

PYTHONPATH=src python -m pcl --help
exit 0
```

The four loaded/distributed `project-control-loop` Skill copies were unchanged
and remain byte-identical at SHA-256
`46dbb9640da5a6d256ab63aba0bb3bcdf9074f8305667c49adaf9b229008a30c`.

Source-tree strict validation was clean before Evidence recording. The
replacement is recorded through the PCL CLI, followed by strict validation,
render, and read-only audit.

## Preserved boundaries

No schema migration, dependency, override/force/lite/config bypass, telemetry,
human-approval fabrication, contract weakening, push, main-checkout change,
Task completion/removal, or external operation was introduced.

Task `T-0002` remains `in_progress`, Story `US-0002` remains draft, and Tests
`TC-0014`–`TC-0019` remain planned. The known Low five remain deferred: Task
list N+1, baseline normalizer event-ID equivalence, and the existing P0-A Low
three.
