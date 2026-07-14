# 0170 exit-status-aware Skill usage validation

Date: 2026-07-14

## Scope

- Feature: `F-0032`
- Story: `US-0030`
- Test: `TC-0093`
- Runtime surface: `pcl report skill-usage`
- Schema/dependencies: unchanged

## Red reproduction

Command:

```bash
PYTHONPATH=src pytest -q tests/test_skill_usage_report.py \
  -k 'uses_codex_result_status or uses_claude_success_status'
```

Result before the implementation: `2 failed, 11 deselected`. Successful Codex
and Claude results both attributed historical finish-check, timeout,
guarded-block, and command-error wording as fresh friction.

## Regression coverage

The focused fixtures now prove:

- a typed successful Codex PCL result suppresses incidental failure wording;
- a truncated non-failed `report skill-usage` result cannot recursively create
  its displayed findings;
- a typed `COMPLETED_WITH_RISK` completion outcome remains classified;
- a typed failed Codex result keeps failure friction;
- Claude `is_error: false` and `is_error: true` preserve the same boundary;
- an explicitly failed self-report remains classifiable.

## Frozen-window dogfood

Command:

```bash
PYTHONPATH=src python -m pcl report skill-usage \
  --since 2026-06-14 --until 2026-07-14 --json
```

The same local window was evaluated immediately before and after the fix.
Concurrent local logs can increase total command counts, so the comparison is
limited to the reproduced self-observation signals.

| Signal | Before | After | Leading command after |
|---|---:|---:|---|
| `finish_checks_not_configured` | 2 occurrences / 1 session | absent | none |
| `guarded_execution_blocked` | 2 occurrences / 1 session | absent | none |
| `timeout` | 20 occurrences / 12 sessions | 16 / 9 | `finish` |
| `completed_with_risk` | 8 occurrences / 3 sessions | 6 / 3 | `goal close` |
| `command_error` | 159 occurrences / 60 sessions | 158 / 59 | `validate` |

The two false P0 candidates disappeared. Remaining candidates start at P1 and
are no longer led by `report skill-usage` output.

## Final verification

```text
ruff check .
All checks passed!

PYTHONPATH=src pytest -q
994 passed, 1 skipped in 391.92s

git diff --check
exit 0
```

One accidentally duplicated full-suite process was stopped; the retained full
run completed independently with exit code 0.

## Residual risk

- Unknown adapter result shapes keep best-effort text classification and can
  still undercount or overcount until a supported status envelope is added.
- A mixed shell call containing both `report skill-usage` and another PCL
  command is not treated as a pure self-report and retains conservative output
  classification.
- The report remains advisory; remaining command-error and timeout clusters
  require separate sanitized reproductions before product changes.
