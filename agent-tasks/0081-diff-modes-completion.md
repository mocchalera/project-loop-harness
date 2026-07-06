# Task 0081: Diff Modes Completion

## Goal

Complete the diff-source story for `pcl impact --diff`. Today the modes
are worktree-vs-HEAD (default), worktree-vs-`--base <ref>`, and
provided diffs (stdin / file / inline). AI agents constantly create new
files and stage partial work; impact receipts must be able to cover
staged, unstaged, and untracked changes explicitly, and every mode must
identify itself unambiguously in `diff_source` / provenance.

The factual untracked omission warning already ships (0078). This task
adds the modes themselves and makes the warning mode-aware.

## Design constraints (agreed, do not relitigate)

- The DEFAULT mode does not change: no flags still means
  worktree-vs-HEAD, tracked files only. Do not complicate the default.
- Every mode yields a unique, documented `diff_source` string and
  provenance entry; receipts and summaries carry them unchanged.
- The untracked omission warning is factual and mode-aware: present
  when untracked files are excluded, absent (or replaced by an
  inclusion count) when they are included.
- No new runtime dependencies, no schema migration; `impact` /
  `context-receipt/v0` evolve additively only.

## Scope

### 1. New mode flags on `pcl impact`

- `--staged`: diff of the index vs HEAD (`git diff --cached`).
  `diff_source: "staged-vs-HEAD"`. Combines with `--base <ref>` as
  `staged-vs-<ref>` only if git semantics make that meaningful;
  otherwise reject the combination with a typed error — decide from
  git behavior, document the decision.
- `--unstaged`: diff of the worktree vs the index (`git diff`).
  `diff_source: "worktree-vs-index"`. Reject `--base` with a typed
  error (the comparison target is the index by definition).
- `--include-untracked`: augments the selected git-based mode with
  untracked files (`git ls-files --others --exclude-standard`),
  represented as added files with full content counted the same way
  other added files are. Works with the default mode, `--base`, and
  `--all-changes`; rejected with provided diffs (stdin/file/inline)
  via a typed error. `diff_source` gains a documented marker (e.g.
  `"+untracked"` suffix) and provenance records the untracked file
  count.
- `--all-changes`: convenience for worktree-vs-HEAD plus
  `--include-untracked` (i.e. everything not committed). Must produce
  the same result as the equivalent flag combination (test this
  equivalence).
- `--base auto`: infer the default branch — try, in order,
  `origin/HEAD` symbolic ref, then local `main`, then `master`; typed
  error listing what was tried when none resolves. The resolved ref
  appears in provenance (`base_ref` resolved value, plus a note that
  it was auto-inferred).
- Mutual exclusivity: `--staged`, `--unstaged`, `--all-changes` are
  mutually exclusive with each other and with provided-diff sources;
  violations produce typed errors, not silent precedence.

### 2. Mode-aware untracked warning

- Modes that exclude untracked files (default, `--base`, `--staged`,
  `--unstaged`): keep the factual untracked omission warning in
  impact output, receipts, and `code-context-summary/v0` (0078
  behavior).
- Modes that include untracked files (`--include-untracked`,
  `--all-changes`): the warning is absent; instead the summary carries
  an additive `untracked_included_count`.
- Provided diffs keep their current warning semantics (0078 already
  handles diff-source-conditional wording).

### 3. Empty-diff guidance per mode

- The existing empty-diff guidance becomes mode-aware: e.g. empty
  `--staged` suggests staging changes or using the default mode; empty
  worktree-vs-HEAD with untracked files present suggests
  `--include-untracked`. Keep messages short and factual.

### 4. Documentation

- `docs/code-context.md`: a mode table — flag combination →
  `diff_source` value → what is compared → whether untracked files are
  included — plus the staged/unstaged/untracked explanation and the
  `--base auto` resolution order.

## Acceptance Criteria

- Each mode produces its unique documented `diff_source`; a test
  enumerates all supported flag combinations and asserts uniqueness
  and provenance content.
- `--include-untracked` receipts include untracked files as candidate
  context (added-file role) and record the untracked count in
  provenance; the untracked omission warning is absent and
  `untracked_included_count` is present in the summary.
- `--all-changes` equals default + `--include-untracked` (equivalence
  test on the same fixture repo).
- `--base auto` resolves per the documented order; unresolvable case
  yields a typed error naming the attempted refs.
- Invalid combinations (`--staged --unstaged`, `--include-untracked`
  with a provided diff, `--unstaged --base <ref>`) produce typed
  errors.
- Empty-diff guidance differs by mode and is asserted in tests.
- Existing default-mode behavior is byte-stable for JSON contracts
  (regression test), aside from documented additive fields.
- `ruff check .` passes; full `python3 -m pytest` passes (365 currently
  green, plus new tests); `pcl init` smoke against a temp dir passes.
- No new runtime dependency, no schema migration, additive contract
  evolution only.

## Do Not

- Do not change the default mode's comparison target or output shape
  beyond documented additive fields.
- Do not read `.gitignore`d files under `--include-untracked`
  (`--exclude-standard` semantics are the boundary); sensitive-pattern
  omission applies to untracked files exactly as to tracked ones.
- Do not add `safe_to_continue` or any go/no-go field.
- Do not add embeddings, Tree-sitter, call graphs, or semantic
  retrieval.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
