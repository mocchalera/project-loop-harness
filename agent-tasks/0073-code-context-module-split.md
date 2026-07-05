# Task 0073: Code Context Module Boundary Split

## Goal

Split the 1,850+ line `src/pcl/code_index.py` monolith into a
`src/pcl/code_context/` package with clear module boundaries, before the
v0.1.10 staleness work and the v0.2 Context Pack bridge pile more code onto
it. This is a pure refactor: zero behavior change, zero contract change,
zero new features.

## Background

- `src/pcl/code_index.py` currently holds scanner, DB store, search, diff
  parser, impact analyzer, receipt writer, and eval in one file (~1,853
  lines after task 0071/0072).
- Tasks 0074 (snapshot consistency) and 0075 (diff source modes) touch
  search/receipts and diff/impact respectively; after this split they can
  proceed in parallel on separate modules instead of contending on one file.
- Ordering note: this task runs AFTER 0072 (sensitive omission) so the
  safety fix ships first and is carried through the split, and BEFORE
  0074/0075.

## Scope

- Create `src/pcl/code_context/` with approximately this layout (adjust
  names only with a documented reason):

  ```text
  src/pcl/code_context/
    __init__.py          # public API re-exports
    scan.py              # walk, ignore/sensitive rules, hash, language
    symbols.py           # symbol-lite extraction
    test_hints.py        # test hint heuristics (filename + ast imports)
    store.py             # code_index_runs / code_index_files read+write
    search.py            # lexical search + ranking
    diff.py              # git/synthetic unified diff parsing
    impact.py            # likely-impacted + verification suggestions
    receipts.py          # context-receipt/v0 artifact writing
    eval.py              # retrieval fixture evaluation
  ```

- Keep `src/pcl/code_index.py` as a thin facade that re-exports the public
  names other modules and tests import today, so no import site outside the
  new package needs to change in this task. The facade must contain no
  logic.
- Move code with `git mv`-friendly, history-preserving commits where
  practical; at minimum keep the facade so `git log --follow` remains
  useful.
- Do not change any CLI flag, output field, contract version, DB access
  pattern, or event emission. Byte-identical `--json` output for
  `pcl index build/status`, `pcl code search`, `pcl impact --diff`, and
  `pcl eval retrieval` on the same inputs.

## Acceptance Criteria

- Full `python3 -m pytest` passes with the pre-split test expectations
  unchanged (tests may be reorganized to mirror the new modules, but
  assertions must not weaken).
- `ruff check .` passes.
- `pcl init` smoke against a temp directory passes.
- A determinism check: run `pcl index build` + `pcl impact --diff` on a
  fixture before and after the split and diff the JSON outputs — identical
  except fields that are inherently run-scoped (ids, timestamps, paths).
- `src/pcl/code_index.py` is under ~100 lines and contains only re-exports.
- No module in `code_context/` exceeds ~500 lines.
- No schema migration, no dependency, no contract version bump.

## Do Not

- Do not fix bugs, tune ranking, or add features "while we're in here" —
  file follow-up notes instead. Behavior changes hide in refactors and this
  task must stay reviewable as a pure move.
- Do not change public CLI behavior or JSON output shapes.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
