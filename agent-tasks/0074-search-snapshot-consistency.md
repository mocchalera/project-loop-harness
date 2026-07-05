# Task 0074: Search Staleness and Snapshot Consistency

## Goal

Make it impossible to misread whether a `pcl code search` result reflects
the index snapshot or the current working tree. Today search targets files
listed in the latest index but reads current working-tree content, so after
an edit the content shown is fresh while the symbol summary, hash, and
ranking inputs are stale — and nothing in the output says so. `pcl impact`
already surfaces staleness warnings; search must reach the same standard.

## Background

- `docs/code-context.md` states the index is a snapshot and the working
  tree is source of truth. That design stands; this task makes the
  snapshot/working-tree boundary visible per result instead of implicit.
- Depends on task 0073: implement inside `code_context/search.py` and
  `code_context/receipts.py`, not the old monolith.
- The v0.1.9 review flagged this as "search と snapshot の整合性が揺れやすい"
  and asked for `snapshot_consistency` in both search output and receipts.

## Scope

- Add a per-result `snapshot_consistency` field to `pcl code search --json`
  with values:
  - `fresh` — current file hash matches the indexed hash,
  - `modified_since_index` — file exists but hash differs,
  - `missing_from_worktree` — indexed but no longer present,
  - `not_hashed` — indexed without a hash (large/binary skip); include the
    skip reason.
  Compute lazily per returned result only (hash the handful of result
  files, not the whole tree) so search stays fast.
- Add a top-level `staleness_warnings` summary to search JSON output
  (count + affected paths), mirroring the existing impact vocabulary.
- Text output: mark non-fresh results with a short, human-readable warning
  line; keep it one line per affected result.
- Add the same `snapshot_consistency` information to
  `context-receipt/v0` artifacts (additive field on
  `included_candidate_context` entries) so receipts state whether each
  included candidate was fresh at receipt time.
- When the latest index run is older than the current git HEAD (HEAD moved
  since index build), say so once in search output, and suggest
  `pcl index build` — phrased as a suggestion, consistent with `pcl next`
  tone, not an error.
- Document the field and its values in `docs/code-context.md`.

## Acceptance Criteria

- Fixture test: build index, modify one indexed file, delete another, then
  search terms hitting both — results carry `modified_since_index` and
  `missing_from_worktree` respectively, an untouched file reports `fresh`,
  and `staleness_warnings` counts exactly the non-fresh results.
- Hash-skipped (large/binary) files report `not_hashed` with a reason.
- `pcl impact --diff` receipts include per-candidate
  `snapshot_consistency`, and existing receipt consumers/tests still pass
  (additive change only).
- Epistemic honesty preserved: the new fields describe file states
  ("hash differs"), never agent cognition; extend the existing vocabulary
  contract test to cover the new fields.
- Determinism: repeated runs on an unchanged tree produce identical JSON.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init` smoke
  against a temp directory passes.
- No schema migration, no dependency, no contract version bump
  (`code-search/v0` and `context-receipt/v0` evolve additively).

## Do Not

- Do not re-hash the entire tree on every search; per-result lazy checks
  only.
- Do not auto-rebuild the index; suggest, never mutate.
- Do not add daemons or file watchers.
- Do not add embeddings, Tree-sitter, call graphs, or semantic retrieval.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
