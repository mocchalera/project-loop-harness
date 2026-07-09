# 0117: Target-specific refresh command in code-context Markdown

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: context/markdown
Origin: third-party v0.3.0 post-release review (P1②). Sakamoto approved the
recommended plan 2026-07-09 (integrity pair 0116+0117 first).

## Problem

The JSON context pack exposes a target-specific refresh command
(`suggested_refresh_commands` ends with `pcl impact --diff --for-task T-XXXX
--json` / `--for-job J-XXXX --json`; see `context.py:313,431` and the JSON tests
at `tests/test_context.py:1626,1660,1694`). But the **Markdown** safety section
`_render_code_context_safety_section` (`context.py:1001-1027`) hardcodes a
generic line in both the `missing_receipt` and `receipt_unavailable` branches:

```
Next action: `pcl index build --json`, then `pcl impact --diff --json`.
```

An agent reading the Markdown pack (many workers read Markdown, not JSON) is told
to run the **unbound** `pcl impact --diff --json`, which produces an unbound
receipt — the exact anti-pattern v0.3.0's target binding exists to prevent. The
stamped `summary` already carries the target: `relevance.target_id`,
target-specific `next_actions` (set for `missing_receipt` in
`_stamp_code_context_pack_facts`, `context.py:827-831`), and a target-rewritten
`refresh_replay` (`_target_refresh_replay`). The Markdown renderer simply ignores
them.

## Scope

1. In `_render_code_context_safety_section`, replace the hardcoded generic
   "Next action" line in **both** the `missing_receipt` and `receipt_unavailable`
   branches with commands derived from the **same** target-specific source the
   JSON uses: `recommended_refresh_commands(summary)` (already imported into
   `context.py:12`). Render them as the "Next action" line so Markdown and JSON
   cannot diverge.
2. Establish the invariant explicitly: **the Markdown safety "Next action"
   commands equal the JSON `suggested_refresh_commands`** for the same pack.
   Whatever list drives `pack["suggested_refresh_commands"]` must be what the
   Markdown line renders — one source, two renderings.
3. If `recommended_refresh_commands(summary)` is empty for some state, fall back
   to the prior generic text (do not crash / emit an empty line); target-bound
   states are the ones that matter here.

## Invariants (what to protect)

- No behavioral change to the JSON pack; only the Markdown string changes.
- For a task pack the rendered command contains `--for-task <task_id>`; for a job
  pack, `--for-job <job_id>`. The `pcl index build --json` prelude is preserved
  if it is part of `recommended_refresh_commands`.
- `## Code Context Safety` heading and the surrounding "Receipt selection and
  freshness facts" lines are unchanged.
- No new claim vocabulary; this is a command-string fix only.

## Non-scope

- Read-side agreement / mismatch handling (0116).
- JSON `suggested_refresh_commands` (already target-specific).
- Any change to `recommended_refresh_commands` / `refresh_replay` themselves.

## Acceptance

- New/updated test on the **Markdown**: for a `missing_receipt` task pack the
  safety section contains `pcl impact --diff --for-task T-XXXX --json` and does
  **not** contain a bare `pcl impact --diff --json` line; the job pack variant
  contains `--for-job J-XXXX`. Add the equivalent assertion for the
  `receipt_unavailable` branch.
- A test asserts the equivalence invariant: the Markdown safety "Next action"
  commands match `pack["suggested_refresh_commands"]` for the same pack.
- Existing `"## Code Context Safety" in pack["markdown"]` assertions
  (`tests/test_context.py:1076,1528,1896` etc.) stay green.
- Full `pytest` green; live smoke: a `context pack --task T-XXXX
  --include-code-context` with no receipt shows the target-specific command in
  the rendered Markdown.
