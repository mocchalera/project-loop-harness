# 0170: Exit-status-aware Skill usage friction

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** M
- **Dependencies:** 0166, 0167
- **DB schema:** no change
- **Human approval:** Story US-0030 approved in Cockpit on 2026-07-14

## User problem

The fixed-window local Skill usage report can classify warning-like text from a
successful tool result as a fresh failure. This is especially visible when
`pcl report skill-usage` prints aggregate findings that mention finish-check,
guarded-block, timeout, or command-error signals from older calls: the report
call itself can then appear as new P0 friction.

## Product outcome

`pcl report skill-usage` uses explicit Codex and Claude tool-result status when
available. Successful results do not create failure friction from incidental
output text. Actual failed results retain their existing classification, and a
successful typed completion result still records `completed_with_risk`.

## Scope

1. Recognize the supported Codex success/failure result envelope without
   retaining raw result data.
2. Preserve Claude's explicit `is_error` result state instead of reducing it
   to failure-only information.
3. Suppress finish-check, timeout, guarded-block, and command-error patterns for
   explicitly successful results.
4. On explicit success, count `completed_with_risk` only from a typed
   completion outcome rather than an incidental text mention.
5. Do not classify a non-failed `report skill-usage` result from its own
   aggregate output, including when that long output is truncated before its
   success field can be parsed.
6. Preserve current best-effort classification for adapters whose result
   status is unknown.
7. Re-run the frozen 2026-06-14 through 2026-07-14 local dogfood window.

## Invariants

- No raw command, argument, output, prompt, path, identifier, or workspace name
  appears in the report.
- No database migration, dependency, network request, external transmission,
  daemon, or automatic state change.
- Exit status affects classification only; command and Skill-use counts remain
  compatible.
- A non-zero or explicit-error result still triggers retry attribution.
- Unknown transcript shapes are not silently treated as successful.

## Acceptance

1. A successful Codex result containing historical failure wording emits no
   failure friction.
2. A failed Codex result with the same wording still emits attributed failure
   friction and can seed a matching retry.
3. A Claude `tool_result` with `is_error: false` suppresses incidental failure
   wording; `is_error: true` remains a failure.
4. A successful typed completion outcome of `COMPLETED_WITH_RISK` remains
   classified, while a prose mention does not.
5. A truncated successful `report skill-usage` output does not self-create
   friction candidates; an explicitly failed report still can.
6. Existing unknown-status fixtures and privacy guarantees remain compatible.
7. Focused tests, `ruff check .`, full `pytest`, strict validation, rendering,
   and the frozen-window dogfood run pass.

## Non-goals

- Inferring success from arbitrary shell output.
- Reconstructing full command pipelines or per-command statuses.
- Changing the `skill-usage-report/v1` schema.
- Automatically applying or publishing improvement candidates.
