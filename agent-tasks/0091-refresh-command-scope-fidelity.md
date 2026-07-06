# Task 0091: Refresh Command Scope Fidelity (P1)

**Status: retroactive record. Implemented in commit `204a857` before
this spec was filed (pulled forward from the v0.1.12 review agenda's
post-v0.2 slot because it landed together with the distribution
refresh). This file exists to keep the task ledger complete; do not
re-implement.**

## Why

`suggested_refresh_commands` was honest about being a regeneration
suggestion (task 0084) but not about scope: if the latest receipt was
produced with `--include-untracked` or `--base main`, suggesting a
bare `pcl impact --diff --json` silently changes the diff scope on
replay. For a product whose value is reproducible context provenance,
refresh suggestions should preserve the recorded scope when they can,
and say so when they cannot (v0.1.12 review agenda, section 4.3).

## What was implemented (204a857)

- `src/pcl/code_context/summary.py` gained `refresh_replay(summary)`,
  returning `{fidelity, commands, reason}`:
  - `scope_preserving`: commands rebuilt from the receipt's recorded
    `diff_source` (re-applying `--include-untracked`, `--base <ref>`,
    `--staged`, `--unstaged` where recorded);
  - `generic`: scope could not be fully reconstructed; commands fall
    back to the staleness-aware defaults;
  - `unavailable`: no replayable receipt scope; commands fall back to
    `next_actions`.
- The summary embeds `refresh_replay`;
  `recommended_refresh_commands()` now prefers replay commands, so
  context packs' `suggested_refresh_commands` inherit scope fidelity
  without a pack contract change.
- Base refs are shell-quoted via `shlex` when echoed into commands.

## Verification

- `tests/test_code_context_summary.py` / `tests/test_context.py` /
  `tests/test_code_index.py` gained fidelity-per-branch coverage in
  204a857 (scope-preserving, generic, unavailable).
- Epistemic boundary held: fidelity labels describe command
  reconstruction only; they make no claim that replay yields an
  identical diff (the working tree may have moved).
