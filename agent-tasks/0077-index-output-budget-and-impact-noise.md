# Task 0077: Index Output Budget and Impact Session-Path Noise

## Goal

Fix two output-ergonomics problems found by dogfooding on 2026-07-05.

1. `pcl index build --json` printed roughly 84k tokens of JSON on this
   repository because it inlines the full per-file index (hashes,
   symbols, test hints for every file). Agents consume this output
   directly; a machine-context command that costs a third of a context
   window per call defeats PLH's own token-budget philosophy.
2. `pcl impact --diff` on a working tree whose only changes are tracked
   `.claude/` session files buries the signal: index-excluded session
   paths appear as changed/omitted noise BEFORE any real implementation
   diff, because git diff reports them even though `pcl.yaml`
   `code_index.exclude` keeps them out of the index.

## Scope

### Index build/status output budget

- `pcl index build --json` and `pcl index status --json` default to a
  SUMMARY payload: run metadata, `file_count`, `indexed_bytes`,
  `ignored_count`, `sensitive_omitted_count`, `language_counts`,
  staleness warnings, and counts of ignored/hash-skipped entries — but
  NOT the per-file `files` array and NOT the full `ignored` array.
- Full detail moves behind explicit access:
  - `--include-files` restores the current full inline payload,
  - additionally write the full index detail as a deterministic JSON
    artifact under `.project-loop/` (e.g. `cache/` or the existing
    dashboard-data location pattern), and include its path in the
    summary payload as `detail_path`, so agents can read exactly the
    slice they need instead of receiving everything on stdout.
- Text (non-JSON) output keeps its current one-line summary behavior.
- Summary payload must remain deterministic; contract evolves additively
  (`code-index/v0` keeps its version; document the default change in
  docs/code-context.md and release notes as a breaking-ish CLI behavior
  change with the `--include-files` escape hatch).
- Update any internal callers/tests that relied on the inline `files`
  array to either pass `--include-files` or read `detail_path`.

### Impact session-path noise separation

- In `pcl impact --diff` output and `context-receipt/v0`, changed files
  whose paths match index exclusions (configured `code_index.exclude`,
  default excludes, or sensitive patterns) move OUT of the main
  `changed_files` / `omitted` flow into a separate additive section
  `excluded_changed_files: [{path, reason}]`.
- Ordering: real (indexable) changed files come first in
  `changed_files`; `excluded_changed_files` carries the session/state
  noise with its exclusion reason (e.g.
  `code_index.exclude:.claude/`).
- `likely_impacted` and `verification_suggestions` must be computed only
  from indexable changed files (verify this is already true after the
  0071/0072 guards; add a regression test either way).
- Text output prints excluded changed paths as a single summarized line
  (count + first few paths), not one line per session file.
- Document the new section in docs/code-context.md.

## Acceptance Criteria

- On a fixture project sized to make the difference visible, the default
  `pcl index build --json` payload is dramatically smaller than the
  `--include-files` payload (assert the default payload contains no
  `files` array and that `detail_path` exists and parses back to the
  full deterministic detail).
- `pcl index status --json` likewise summary-by-default.
- Impact fixture with a mix of real source changes and `.claude/`-style
  excluded changes: `changed_files` contains only the real changes,
  `excluded_changed_files` carries the noise with reasons, receipts
  include the same split, and `likely_impacted` /
  `verification_suggestions` are unaffected by the excluded paths.
- Existing receipts remain valid `context-receipt/v0`; additive only.
- `ruff check .` passes; full `python3 -m pytest` passes (337 currently
  green); `pcl init` smoke against a temp dir passes.
- No schema migration, no dependency, no contract version bump.

## Do Not

- Do not silently drop information: everything removed from the default
  payload must be reachable via `detail_path` or `--include-files`.
- Do not change what gets indexed — this task changes reporting, not
  scanning.
- Do not modify `.claude/` git tracking in this task; repo hygiene is a
  separate human decision.
- Do not add embeddings, Tree-sitter, call graphs, or semantic
  retrieval.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
