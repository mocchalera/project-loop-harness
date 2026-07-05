# Task 0075: Explicit Diff Source for Impact

## Goal

Make `pcl impact --diff` state exactly what it compared, and let operators
compare against a chosen base ref. Today the default diff source is
implicit, so a receipt cannot tell a later reader whether the impact
analysis covered staged work, unstaged work, or a branch delta.

## Background

- Decision (approved 2026-07-05): the default diff source is
  **working tree vs HEAD** (staged + unstaged combined). Rationale: the
  project dogma is "working tree is source of truth", and the default
  should follow it. Ambiguity is removed by labeling, not by mode
  proliferation.
- Scope decision: the review proposed `--staged` / `--unstaged` /
  `--base <ref>` / `--include-untracked`. Only `--base <ref>` and explicit
  `diff_source` labeling are in scope now; the other modes wait until
  dogfooding demonstrates need.
- Depends on task 0073: implement inside `code_context/diff.py` and
  `code_context/impact.py`.
- Can run in parallel with task 0074 (different modules).

## Scope

- Add a `diff_source` field to `pcl impact --diff` JSON output and to the
  `context-receipt/v0` artifact (additive). Values:
  - `worktree-vs-HEAD` — the default when `--diff` is used without a
    piped diff and without `--base`,
  - `worktree-vs-<ref>` — when `--base <ref>` is given,
  - `provided-diff` — when a diff is piped in via `--diff -`; record that
    the diff came from stdin and PLH cannot attest to its provenance.
- Implement `--base <ref>`: run the diff between `<ref>` and the working
  tree. Validate the ref exists first; on an unknown ref, fail with a typed
  command error naming the ref, not a raw git stderr dump.
- Default behavior when `--diff` is used with no stdin diff and no
  `--base`: produce the worktree-vs-HEAD diff internally (staged +
  unstaged combined) instead of requiring a piped diff. Keep the existing
  piped-diff path fully working.
- When the resulting diff is empty, do not emit an empty receipt silently:
  say there is nothing to analyze for the stated `diff_source` and suggest
  likely next operations (e.g. `--base <default-branch>` if HEAD equals the
  working tree), in `pcl next` tone.
- Record `diff_source` (and `base_ref` when applicable) in the receipt and
  in the impact JSON, and document the semantics in
  `docs/code-context.md`, including exactly what the default covers and
  that untracked files are not part of worktree-vs-HEAD diffs.

## Acceptance Criteria

- Fixture tests cover: default worktree-vs-HEAD (staged-only change,
  unstaged-only change, both), `--base <ref>` against an older commit,
  piped diff, unknown ref error, and empty-diff guidance. Each asserts the
  correct `diff_source` value in both JSON output and receipt.
- Receipts remain valid `context-receipt/v0`; additive evolution only, and
  existing receipt tests keep passing.
- Empty diff produces actionable guidance, exit code consistent with
  existing no-op command conventions, and no receipt artifact.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init` smoke
  against a temp directory passes.
- No schema migration, no dependency, no contract version bump.

## Do Not

- Do not add `--staged`, `--unstaged`, or `--include-untracked` in this
  task; note them as future options in docs instead.
- Do not shell out to git in ways that depend on user config (pager,
  external diff drivers); use plumbing-safe invocations.
- Do not add embeddings, Tree-sitter, call graphs, or semantic retrieval.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
