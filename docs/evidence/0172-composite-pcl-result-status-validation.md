# 0172 composite PCL result status validation

Date: 2026-07-14

## Scope

- Goal: `G-0033`
- Task: `T-0056`
- Feature: `F-0034`
- Story: `US-0032`
- Test: `TC-0096`
- Runtime surface: `pcl report skill-usage`
- Schema/dependencies: unchanged

## Reproduction

The pre-change frozen-window report treated successful composite PCL output as
unknown when it contained multiple JSON results, unrelated shell preamble, or a
truncated long result. Incidental text then produced these false candidates:

- `finish_checks_not_configured`: 1 occurrence, P0 candidate
- `guarded_execution_blocked`: 1 occurrence, P0 candidate
- `timeout`: 6 occurrences across successful lifecycle commands

A failing regression fixture reproduced the same behavior with successful
Goal/Story text and a truncated Codex result. It also proved that explicit
`ok:false` and typed `COMPLETED_WITH_RISK` must remain classified.

## Implemented contract

- Complete whitespace-separated JSON streams are parsed without retaining
  their content.
- Compact standalone JSON after non-PCL preamble is recognized.
- Any parsed top-level `ok:false` wins and remains a failure.
- One structured result per normalized PCL command establishes success.
- A supported Codex `Script completed` wrapper establishes success for
  truncated PCL output when no explicit failure is present.
- Typed completion outcomes are extracted across composite JSON.
- Unknown adapters without supported status evidence retain prior best-effort
  classification.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_skill_usage_report.py
15 passed in 0.49s

ruff check .
All checks passed!

git diff --check
exit 0

PYTHONPATH=src pytest -q
998 passed, 1 skipped in 164.77s
```

The post-change 2026-07-14 dogfood rerun reported zero
`finish_checks_not_configured`, zero `guarded_execution_blocked`, and zero
`timeout` friction. The remaining typed `COMPLETED_WITH_RISK` and explicit
command-error signal were preserved, along with help and failure-driven retry
observations.

## Residual risk

- Composite result recognition is limited to supported Codex/Claude shapes and
  compact PCL JSON boundaries; unknown adapters remain conservative.
- A wrapper can prove tool completion but cannot reconstruct exact stdout
  ownership inside an arbitrary shell pipeline. Explicit typed failures still
  take precedence, and the report remains advisory rather than proof of a
  product defect.
