# Maintainer entry hardening and CLI split contract

This document freezes the observable behavior boundary for a future staged
split of `src/pcl/cli.py` and `src/pcl/commands.py`. It also defines the source
checkout diagnostic that protects verification from a stale editable install
or a neighboring worktree.

## Source-checkout doctor diagnostic

`pcl doctor` applies the check only when the target root factually looks like
the Project Loop Harness source repository:

- `pyproject.toml` declares `name = "project-loop-harness"`; and
- `<root>/src/pcl` exists.

The running package root is the resolved directory containing the loaded
`pcl.validators` module. The expected package root is resolved from
`<root>/src/pcl`.

When those paths differ, doctor emits a warning finding with code
`development_runtime_source_mismatch`. The finding includes both paths and a
source-pinned retry command of this form:

```bash
PYTHONPATH=/absolute/checkout/src python -m pcl \
  --root /absolute/checkout --json doctor
```

The command diagnoses with the selected checkout. It does not reinstall,
repoint, delete, or mutate any Python environment. Ordinary adopted projects
do not receive the finding, and `pcl validate` does not run this development
environment check.

## Frozen behavior boundary

Moving code between modules must not intentionally change any of these
surfaces:

1. command and subcommand names, positional arguments, flags, defaults, help
   text, and parser acceptance;
2. JSON keys, value types, ordering guarantees, text output, and exit codes;
3. typed error codes, detail fields, and zero-mutation rejection behavior;
4. SQLite transactions, event names and payloads, outbox projection, Evidence
   and relationship writes, and lock boundaries;
5. human gates, `requires_human`, `safe_to_run`, and `run_policy` semantics;
6. deterministic generated artifacts and dashboard-data contracts;
7. bundled Skill command examples and source/wheel/sdist entry points.

Any intentional change to those surfaces is separate feature work with its own
Story, Tests, migration or compatibility decision when applicable, and
Evidence. It must not be hidden inside a module move.

## Staged extraction order

### Stage 0 — Contract baseline

- Keep parser and dispatch in place.
- Record full-suite, distribution, Skill-parser, golden-path, and JSON-contract
  results on the same revision.
- Add characterization tests before moving an uncovered branch.

### Stage 1 — Pure presentation helpers

- Move JSON/text formatting helpers that perform no state access.
- Preserve imports through narrow compatibility re-exports when tests or
  internal callers rely on them.
- Gate: formatter tests, CLI JSON snapshots, help/parser tests, then full suite.
- Implementation task: `agent-tasks/0184-cli-stage1-presentation-extraction.md`.

### Stage 2 — Read-only command handlers

- Extract doctor, guide, context/read, status, and report handlers by command
  family without moving parser definitions in the same slice.
- Pass `ProjectPaths` and parsed arguments explicitly; no hidden global state.
- Gate: read-only zero-mutation assertions, output parity, distribution smoke,
  then full suite.
- First implementation task: `agent-tasks/0185-cli-stage2-guide-handler-extraction.md`.

### Stage 3 — Mutating command handlers

- Extract one lifecycle family at a time: Goal/Task, Feature/Story/Test,
  Evidence, Workflow, then profile/authorization.
- Keep transactions and `append_event` ownership in the current service layer;
  handlers remain orchestration only.
- Gate: command-family mutation tests, event/outbox/audit tests, failure
  zero-trace tests, then full suite.

### Stage 4 — Parser construction

- Split parser builders only after handler extraction has stabilized.
- Keep one top-level `build_parser()` and the existing console entry points.
- Gate: complete parser-example matrix, `--help` surfaces, source/wheel/sdist
  smoke, and full CI matrix.

## Slice acceptance gate

Every extraction commit must satisfy:

```bash
ruff check .
pytest <affected command-family tests>
pytest tests/test_skill_command_examples.py tests/test_distribution.py
pytest
PYTHONPATH=src python -m pcl --root . --json doctor
PYTHONPATH=src python -m pcl --root . --json validate --strict
PYTHONPATH=src python -m pcl --root . --json render
git diff --check
```

If output or event parity changes unexpectedly, stop the extraction and revert
that slice without weakening the contract tests.
