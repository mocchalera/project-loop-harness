# 0164 Codex review remediation evidence

## Review receipt

- Reviewer: independent Cockpit Codex task `e491f178`
- Reviewed commit: `fae1c83`
- Review Evidence: `E-0231`
- Verdict: `Changes required`
- Findings: four blocking issues, recorded in
  `docs/reviews/0164-guided-dashboard-codex-final-review.md`

## Repairs

1. `Next` now reports `agent_safe` only when `safe_to_run is True` and the
   action's `run_policy` is `agent_safe`. Idle, human, and manual/waiting states
   remain distinct.
2. Detailed risk and human-decision panels, including raw commands and option
   tables, now live inside the native advanced disclosure. The collapsed view
   contains only the five operator cards.
3. `Done` candidates are reconciled with the current Feature, Test, Goal, or
   Verification state, deduplicated by entity, and no longer use a fixed
   50-event scan window.
4. Regression coverage now includes idle, manual waiting, agent-safe and human
   paths; validation warnings; escaped titles; disclosure boundaries; current
   state supersession; event-window pressure; Goal and Verification completion;
   and exclusion of reason-only Task completion.

## Red-green evidence

Before the repair, the targeted tests reproduced the reviewed behavior:

- manual `continue_goal` rendered the agent-safe sentence;
- risk and decision commands appeared before `<details>`;
- a valid older Test completion was lost behind non-terminal status events;
- historical Feature/Test completion remained eligible after supersession.

After the repair:

- `ruff check src/pcl/renderer.py tests/test_dashboard.py` passed;
- the focused dashboard and distribution command completed with
  `80 passed in 38.38s`;
- `ruff check .` passed;
- `PYTHONPATH=src pytest -q` completed with
  `967 passed, 1 skipped in 404.19s`.

## Visual evidence

Cockpit browser inspection confirmed both states against the current repository
dashboard:

- collapsed: localized `今 / 完了 / 次 / あなたの判断 / 注意点` cards only;
- expanded: all four open review defects and their commands remain inspectable
  inside `詳細なProject Loop情報`.

Captured artifacts:

- `output/playwright/0164-dashboard-remediation-collapsed.png`
- `output/playwright/0164-dashboard-remediation-expanded.png`

The existing 420 px artifact remains valid because no card-grid or responsive
CSS changed during remediation. Fragment anchors and script-free native
disclosure are still covered by the focused suite.
