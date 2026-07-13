# 0164 guided dashboard Codex final review

- **Reviewer:** independent Codex task `e491f178`
- **Reviewed commit:** `fae1c83`
- **Mode:** read-only; no test execution, file edits, PCL mutation, commit, or push
- **Human authorization:** the operator explicitly selected Codex as the
  substitute for the unavailable Claude Fable implementation review
- **Verdict:** Changes required

## Blocking findings

### 1. Manual review work is mislabeled agent-safe

`src/pcl/renderer.py` classifies every non-human, non-idle next action as
`agent_safe`. Actions such as `continue_goal` may have `safe_to_run=false` and
`run_policy=manual_state_transition`, yet the summary says the agent will
continue the next safe step.

Required repair: reserve `agent_safe` for `safe_to_run is True`; map human,
idle, and manual/waiting work separately and add regression coverage.

### 2. Detailed commands remain outside progressive disclosure

The full risk and human-decision panels remain before the native `<details>`
element. Those panels can expose raw commands and detailed decision options on
the first screen, contrary to the operator-summary contract.

Required repair: keep only the five structured summary cards above the
disclosure. Move detailed risk and decision panels into the advanced section,
and assert that raw command markup does not precede `<details>`.

### 3. Done ignores the entity's current state

`_evidence_backed_done_items()` selects historical terminal events but does not
confirm that a Feature is still `done`, a Test is still `passing`, or a Goal is
still `closed`. A later fail, block, or needs-fix transition can therefore leave
stale success in the operator summary. The fixed 50-event scan can also hide
otherwise valid completions.

Required repair: reconcile candidates with current entity state, deduplicate by
entity, remove the arbitrary event-window loss, and cover superseded and
high-volume histories.

### 4. Summary-state coverage is incomplete

The committed tests do not directly cover idle, manual waiting, validation
warnings, goal closure, all four Done sources, reason-only Task exclusion,
superseded terminal states, or operator-summary escaping. The validation report
therefore overstates coverage.

Required repair: add focused regression tests for those semantics and update
the validation report with the measured result.

## Areas confirmed by the reviewer

- HTML-only derivation preserves `dashboard-data/v1`.
- Japanese summary sentences are composed from structured fields.
- The four Skill copies are identical and define the same presentation moments.
- Native disclosure, script-free rendering, fragment targets, escaping, and
  deterministic ordering are sound apart from the findings above.
- The 420 px visual artifact is readable without horizontal clipping.

## Disposition

The four blocking findings must be repaired and independently re-reviewed
before Feature `F-0026`, Task `T-0047`, and Goal `G-0025` can be closed.
