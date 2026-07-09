# 0122: feature_coverage no-op when everything is already covered (F4)

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: workflows/cli
Origin: ax1-moc1 feedback F4 ("feature_coverage 既存カバレッジ検出で no-op").
Sakamoto directed proceeding 2026-07-09. v0.3.1 final task.

## Problem

`pcl loop run feature_coverage --goal G` always creates a workflow run plus
map/stories/tests jobs, even when every tracked feature is already covered. That
re-proposes the same coverage work and makes the loop feel like it is advancing
when there is nothing new to do (the "同じ種類の提案を繰り返す" friction).

Detect the already-covered state and no-op: create no run, no jobs, no events;
return a clear result saying nothing needs coverage.

## Definitions

- Uncovered feature statuses (coverage work remains): `discovered`, `specified`,
  `needs_test`, `needs_fix` (the same set `_uncovered_feature_next_action` uses).
- Covered feature statuses: `passing`, `done`, `waived`.
- No-op condition: `workflow_id == "feature_coverage"` AND at least one feature
  exists AND no feature is in an uncovered status.
- NOT a no-op: zero features exist (the first feature_coverage run is discovery),
  or any feature is uncovered.

## Scope

- In `run_workflow` (`src/pcl/workflows.py`), after `_validate_target` and before
  inserting the `workflow_runs` row, when `workflow_id == "feature_coverage"` and
  the no-op condition holds, return a no-op result WITHOUT inserting a run, jobs,
  prompts, or events (no `conn.execute` INSERT, no `append_event`, no prompt file
  written, no commit of new state).
- No-op result shape (JSON-serializable, distinguishable from a real run):
  ```
  {"ok": true, "no_op": true, "reason": "feature_coverage_already_covered",
   "workflow_run": null, "jobs": [],
   "covered_feature_count": N, "feature_count": N}
  ```
- Only `feature_coverage` is affected. Other workflows (executor_smoke,
  defect_repair, etc.) are never no-opped by coverage state.
- CLI (`pcl loop run`, cli.py): handle `no_op` in the non-JSON branch (print a
  clear one-line message, e.g. "No workflow run created: all tracked features are
  already covered (N)."); JSON prints the result as-is. Exit 0 either way.

## Invariants (what to protect)

- No-op writes nothing: no `workflow_runs` / `agent_jobs` rows, no events, no
  prompt files, no id allocation. A test MUST assert row/event counts (and next
  `WR-`/`J-` id) are unchanged across a no-op call.
- Non-feature_coverage workflows are unchanged. A covered project can still run
  `executor_smoke` etc.
- Zero-feature and uncovered-feature cases still create a real run (no regression
  to discovery / normal coverage).
- No claim vocabulary; the no-op reason states a fact (all features covered),
  not that the project is complete/correct.
- Additive: no schema change, no migration.

## Non-scope

- Changing feature status semantics or the covered/uncovered sets.
- Goal-scoped feature subsets (features are global; use the global set).
- `pcl next` behavior (already routes uncovered features via
  `_uncovered_feature_next_action`).

## Acceptance

- All features covered (>=1 feature, none uncovered): `pcl loop run
  feature_coverage --goal G --json` returns `no_op: true`,
  `reason: feature_coverage_already_covered`, no run/jobs; row/event counts and
  next ids unchanged.
- One uncovered feature: a real run + jobs are created (no no-op).
- Zero features: a real run is created (discovery).
- `pcl loop run executor_smoke` is unaffected by coverage state.
- `ruff` clean; full `pytest` green (baseline 505; expect > 505).
- Live smoke (`python -m pcl`): cover all features, then `loop run
  feature_coverage` shows the no-op; add an uncovered feature, then it creates a
  run.
