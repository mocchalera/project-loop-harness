# Refactoring completion plan

## Purpose

Complete the behavior-preserving split frozen in
`docs/maintainer-entry-hardening.md`. Stages 1 and 2 are already complete in
Tasks 0184-0188. This plan covers the remaining mutating handlers, the
`commands.py` service split, parser construction, and final distribution
verification.

## Baseline

- Revision: `1ea685a94d0832538278a37054180535596d8450`
- `src/pcl/cli.py`: 4,319 lines; `main()` is 2,183 lines with 366 `if` nodes.
- `src/pcl/commands.py`: 2,444 lines and 73 top-level functions.
- `ruff check .`: passing.
- `pytest`: 1,160 passed, 1 skipped.
- Source-checkout doctor: passing with no findings.
- Strict validation: no errors; three active and 26 historical pre-existing
  warnings remain outside this refactor.

## Frozen boundary

This is a pure refactor. It does not intentionally change commands, flags,
help text, JSON/text bytes, exit codes, typed errors, SQLite writes,
transactions, event/outbox payloads, Evidence behavior, human gates,
generated artifacts, schema, dependencies, or public import surfaces.

## Work sequence

1. **0204 entity lifecycle handlers** — Goal, Task, Feature, Story, Test, and
   Defect CLI orchestration.
2. **0205 execution and evidence handlers** — Loop, Workflow, Jobs, Agent,
   Evidence, Verification, Decision, Escalation, and checkpoint orchestration.
3. **0206 profile and control handlers** — Profile, contract, Evidence Set,
   Work Brief, Gap Report, route/policy, initialization, audit/repair, context,
   index/eval, and remaining command orchestration.
4. **0207 command service split** — move domain mutation/query services,
   next-action routing, and finish planning behind compatibility re-exports
   from `pcl.commands`.
5. **0208 parser construction split** — move parser-family construction behind
   one stable `build_parser()` facade and retain existing entry points.
6. **0209 integrated verification** — run the complete acceptance ladder,
   source/wheel/sdist smoke tests, record Evidence, and close the PCL Goal.

Each implementation task is a separate reviewed commit. A slice stops if
characterization tests reveal output, event, or zero-trace behavior drift.

## Completion criteria

- `cli.py` is a thin entrypoint/facade; command orchestration and parser-family
  construction live in bounded modules.
- `commands.py` is a compatibility facade; service and routing implementations
  live in responsibility-specific modules.
- Existing public imports from `pcl.commands` continue to work.
- Targeted command-family tests, Skill examples, distribution tests, Ruff,
  full pytest, doctor, strict validation, render, and `git diff --check` pass.
- Source, wheel, and sdist entry points expose identical command/help behavior.
- No new dependency, schema migration, external write, or unrelated cleanup.

