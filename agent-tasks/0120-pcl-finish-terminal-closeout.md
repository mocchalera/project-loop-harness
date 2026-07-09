# 0120: `pcl finish` — terminal close-out planner (safe first slice)

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: cli/loop
Origin: ax1-moc1 agent feedback F7 ("終端処理の認知負荷が実装より重い");
growth-plan v0.3.1 Operator Experience. Sakamoto approved proceeding 2026-07-09.

## Problem

Closing out a loop is a long, easy-to-misorder sequence (Golden Path):
`pcl jobs complete` (per job) -> `pcl verification record` -> `pcl loop
complete` -> `pcl goal close` -> `pcl validate --strict` -> `pcl report` ->
`pcl render`. The cognitive load of knowing *what to run, in what order, and
what still blocks closure* is heavier than the work itself. There is no single
command that answers "what is left to finish this, and what needs my decision."

Add `pcl finish`: a terminal close-out **planner** that computes the ordered
remaining steps for the active run and its goal, classifies each, and — only
when asked — runs the safe generation tail. It never fabricates a completion,
verification, or closure.

## Design boundary (non-negotiable)

`pcl finish` MUST NOT assert state on the human's behalf. It never records a
verification, completes a job, completes/fails a run, or closes a goal or
defect. Those are all `safe_to_run=False` / `requires_human` steps in the
existing `next_action` model; `finish` plans them and hands them back as
explicit commands. `finish --execute` runs ONLY `safe_to_run=True` generation
(`pcl validate --strict`, `pcl render`), and only once no state-transition step
remains. This keeps `finish` inside PLH's epistemic discipline: it organizes and
reports, it does not claim work is done.

## Scope

### CLI
Add a top-level `pcl finish [--json] [--execute]` (sibling of `pcl next`).
Optional `--run WR-XXXX` / `--goal G-XXXX` to target explicitly; default is
auto-detect (below). Dispatch in `cli.py` next to the `next` handler; emit
`_print_json({"ok": True, "finish": payload})` for `--json`, else a short
ordered text summary.

### Target detection (reuse existing state model, read-only)
- Auto-detect the active run exactly as `_active_workflow_next_action`
  (`commands.py:1302`) does: newest `workflow_runs` row with status in
  `ACTIVE_RUN_STATUSES`. Its `goal_id` is the goal in scope.
- If no active run: fall back to the newest open goal from `loop_status`
  (`commands.py:309`). If neither exists, return a `finished`/nothing-to-do
  payload (idempotent), not an error.

### Plan (the core, read-only)
Compute the ordered remaining close-out steps and classify each. Reuse the
existing ladder in `_active_workflow_next_action` for the run portion — do not
reinvent it — extracting the same step dicts (`type`, `command`, `reason`,
`requires_human`, `safe_to_run`, produced by `build_next_action`,
`commands.py:340`). Steps, in order:
1. Run close-out ladder (reuse `_active_workflow_next_action` semantics /
   `_job_status_counts`): `continue_workflow` (active jobs remain) ->
   `resolve_workflow_failure` (failed/cancelled jobs) -> `record_verification`
   (all jobs terminal, no approved verification; `requires_human=True`) ->
   `complete_workflow` (approved verification exists).
2. `close_goal`: if the run's goal is not yet `closed`/`cancelled` and the run
   is (or becomes) passed, the remaining step is
   `pcl goal close {goal_id} --summary '...' --verification {verification_id}`
   (`requires_human=True`, `safe_to_run=False`). Include the approved
   `verification_id` when known.
3. Generation tail (only listed as remaining when steps 1-2 are all done):
   `pcl validate --strict` and `pcl render` (`safe_to_run=True`,
   `requires_human=False`). These are read-only / idempotent regeneration.

Payload:
```
{
  "target": {"run": "WR-XXXX"|null, "goal": "G-XXXX"|null},
  "finished": bool,                  # true when no state-transition step remains
  "remaining_steps": [ {type, command, reason, requires_human, safe_to_run} ],
  "next_command": "<first remaining step command>"|null,
  "executed": [ {command, ok} ],     # only with --execute
  "changed": bool                    # only with --execute
}
```

### `--execute` (safe tail only)
- If any `safe_to_run=False` step remains (jobs/verification/run/goal
  assertions): run NOTHING, return the plan, `changed: false`, `next_command`
  set. (You cannot safely generate from non-final state, and you must never run
  the assertion.)
- If no `safe_to_run=False` step remains: run the generation tail
  (`validate --strict`, then `render`) in order, capture each in `executed`,
  set `changed: true` if anything ran. `finished: true`.
- Idempotent: a fully-closed, already-generated loop re-run with `--execute`
  reports `finished: true`, `remaining_steps: []`. Regenerating render is
  acceptable; do not error and do not assert anything.

## Invariants (what to protect)

- `finish` writes NO loop state itself: no verification, job completion, run
  complete/fail, goal/defect close. It only ever *invokes* the existing safe
  read-only generators (`validate`, `render`) under `--execute`, and otherwise
  reads. A test MUST assert that a plan (no `--execute`) changes no rows/events,
  and that `--execute` with a pending assertion changes no rows/events.
- Reuse the existing `requires_human` / `safe_to_run` classification from the
  `next_action` machinery; do not invent a parallel policy. `finish`'s per-step
  flags must match what `pcl next` reports for the same step.
- No new claim vocabulary. `finish` states facts ("all jobs terminal; no
  approved verification exists; next: record verification") — never that work is
  correct, sufficient, or safe.
- Additive: no schema change, no migration.

## Non-scope

- Auto-completing evidenced jobs, auto-recording verifications, or auto-closing
  goals (a possible future opt-in slice; NOT this task).
- `report` generation in the tail (keep the tail to `validate` + `render`;
  reports can be a later addition).
- Feature-coverage / escalation / decision handling — `finish` is scoped to the
  active run + its goal close-out, not the whole `next_action` priority ladder.
- Localization (0121) and any human-gate wording changes.

## Acceptance

- Mid-run (`continue_workflow`): `pcl finish --json` lists the remaining ladder
  with correct `requires_human`/`safe_to_run` per step, `next_command` = jobs
  read/continue; `--execute` runs nothing (`changed:false`) because an assertion
  is pending.
- All jobs terminal, no verification: `next_command` = `verification record`,
  step `requires_human:true`; `--execute` still runs nothing.
- Run passed + verification approved, goal open: `next_command` = `goal close`
  with the `--verification` id; `--execute` runs nothing.
- Everything closed: `finished:true`, `remaining_steps:[]`; `--execute` runs
  `validate --strict` then `render`, reports them in `executed`, `changed:true`;
  a second `--execute` is idempotent.
- Read-only proof test: a plan and a `--execute` with a pending assertion each
  leave evidence/event/row counts unchanged.
- No active run and no open goal: `finished:true`/nothing-to-do, exit 0, no
  error.
- `ruff` clean; full `pytest` green (v0.3.1 baseline 497; expect > 497).
- New `docs/finish.md` (or a `## Finish` section in an existing loop doc, but do
  not touch README / the 0118-owned docs). Live smoke (`python -m pcl`) pasting
  the plan JSON at two ladder stages plus the closed-loop `--execute`.
