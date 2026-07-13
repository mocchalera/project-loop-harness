# 0164 guided dashboard Codex re-review

- **Reviewer:** independent Cockpit Codex task `e491f178`
- **Reviewed remediation commit:** `f8e0122`
- **Mode:** read-only; no test execution, edits, PCL mutation, commit, or push
- **Verdict:** Approve

## Findings

No blocking or minor findings remain.

## Prior finding disposition

1. **Resolved — manual actions mislabeled agent-safe.** `agent_safe` now
   requires both `safe_to_run=True` and `run_policy=agent_safe`; idle, human,
   and manual waiting paths are distinct and directly tested.
2. **Resolved — detailed commands outside disclosure.** Risk, human decision,
   raw command, and detailed panels live inside native `<details>`. Tests and
   the E-0236 collapsed/expanded images confirm the boundary.
3. **Resolved — Done ignored current state.** Done now reconciles terminal
   events with current Feature/Test/Goal/Verification state, deduplicates by
   entity, removes the fixed event window, and excludes superseded success.
4. **Resolved — summary-state test gaps.** Coverage now includes idle, manual,
   agent-safe, human, validation warning, escaping, disclosure boundaries,
   superseded terminals, event pressure, all terminal Done sources, and
   reason-only Task exclusion.

## Contract confirmation

- `dashboard-data/v1` remains unchanged; the summary is HTML-only.
- Japanese text is composed from structured fields and user titles are escaped.
- The four bundled Skill copies remain identical with the four presentation
  moments and host-neutral open-or-link fallback.
- Native script-free disclosure and fragment targets remain intact.
- The reviewer confirmed all four E-0236 manifest members match the committed
  blobs by SHA-256 and accepted the recorded `80 passed`, `967 passed, 1
  skipped`, and ruff results without rerunning them.

## Final verdict

`Approve`
