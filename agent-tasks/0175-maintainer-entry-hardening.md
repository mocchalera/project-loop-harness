# 0175: Maintainer entry hardening

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.0 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0174 publication closeout and first-channel external launch
- **DB schema:** remains 8
- **Evidence:** `docs/evidence/0178-maintainer-entry-hardening.md`

## Goal

Make source-checkout verification identify the recurring wrong-worktree or
stale-editable-install trap, and freeze the observable CLI contract before any
large command-module refactor.

## Scope

1. When `pcl doctor` is run against the `project-loop-harness` source checkout,
   compare the running `pcl` package root with `<checkout>/src/pcl`.
2. Emit a structured `development_runtime_source_mismatch` finding containing
   both paths and a source-pinned retry command when they differ.
3. Keep ordinary adopted projects and a matching source checkout quiet.
4. Document the behavior that future `cli.py` / `commands.py` extraction must
   preserve, the staged extraction order, and the green-test gate for each
   slice.
5. Synchronize the post-launch priority and task indexes.

## Invariants

- The diagnostic is factual; it does not rewrite an editable install or choose
  a worktree for the maintainer.
- No dependency, schema, migration, raw SQL, telemetry, hosted service, or
  automatic external write is added.
- Normal `pcl validate` remains unaffected; the maintainer diagnostic belongs
  to `pcl doctor` configuration advice.
- Existing commands, output keys, typed errors, exit codes, events, mutation
  boundaries, and Skill examples do not change in this slice.
- The CLI split itself is not implemented here.

## Acceptance

1. A source checkout run from another package root emits one structured warning
   with the running root, expected root, and deterministic retry command.
2. A matching source checkout and an ordinary initialized project emit no such
   finding.
3. Targeted tests, full `ruff`, full `pytest`, strict PCL validation, and render
   pass.
4. The split plan freezes observable behavior and provides bounded extraction
   gates before code movement.

## Non-goals

- Repointing pipx, venv, or global Python environments.
- Splitting `cli.py` or `commands.py` in this task.
- v0.5.1 Trace work, event-log compaction, provider execution, or a release.
