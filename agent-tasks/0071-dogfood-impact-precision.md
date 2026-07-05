# Task 0071: Dogfood Feedback — Impact Precision and Index Hygiene

## Goal

Fix the defects and precision problems found while dogfooding Explainable
Code Context v0 (task 0069) against this repository itself on 2026-07-05.
The eval harness quantified the baseline on a realistic fixture:
overall precision 0.1429, recall 0.6667. Every fix below must move those
numbers, and the realistic fixture must ship so the movement is measured.

## Dogfood findings (evidence)

1. DEFECT — diff parser: piping a real historical diff
   (`git diff 9bf3fac~1..9bf3fac | pcl impact --diff - --json`) produced
   `changed_files` entries that are diff CONTENT lines, not paths, e.g.
   `CONTEXT_PACK_CONTRACT_VERSION = "context-pack/v1` and
   `See [docs/context-pack.md](docs/context-pack.md) for the contract shape and`.
   The parser misreads body lines as file headers on real multi-file diffs.
2. DEFECT — precision collapse: `lexical_symbol_reference` matched ~90 of
   256 files at confidence 0.5 because ultra-common symbols ("Project Loop
   Harness", "Command", "Contract", "_json_output") are treated as
   discriminating signals. `verification_suggestions` ballooned into one
   giant pytest command listing dozens of test files. Output at this
   precision is unusable for its purpose (helping a human/agent pick
   verification steps).
3. Index hygiene: harness session files (`.claude/state/`, `.claude/sessions/`,
   `.claude/memory/`, `.agents/`) are indexed because they are git-tracked.
   They dominate real working diffs, pollute `pcl code search` results, and
   cause permanent staleness warnings within minutes of any session activity.
4. Search ranking: `pcl code search` requires all query terms on one line
   and returns results in path order. For "token estimator" the defining
   file `src/pcl/context.py` ranked below README and agent-tasks mentions;
   for "dashboard next_action" the generating code was missed entirely.
5. Recall gap: the test-hint heuristic missed `tests/test_dashboard.py` for
   a `src/pcl/renderer.py` change (no `test_renderer.py` exists; the
   filename heuristic cannot see that test_dashboard exercises the renderer).

## Scope

- Fix the unified-diff parser: only `diff --git` / `+++` / `---` /rename
  headers may introduce paths; body lines must never be parsed as paths.
  Add regression tests using real multi-file diffs from this repo's history
  (commit them as fixture files).
- Add a document-frequency guard to `lexical_symbol_reference`: a symbol or
  phrase present in more than a small fraction of indexed files (pick and
  document a threshold, e.g. >5% of files or >10 files) carries no signal
  and must be dropped as an impact reason. Record dropped symbols in the
  receipt `omitted` with a reason.
- Cap `likely_impacted` (documented threshold, e.g. top 20 by confidence)
  and move the overflow into `omitted` with reasons — silent truncation is
  not allowed, and neither is an unbounded list.
- Keep `verification_suggestions` proportionate: suggest at most a handful
  of targeted test commands; if the confident set is larger, suggest the
  full-suite command instead of enumerating dozens of files.
- Add default index exclude patterns for harness/session noise
  (`.claude/`, `.agents/`, and similar agent-session state), overridable via
  a documented `pcl.yaml` setting (e.g. `code_index.exclude`). Excluded
  files get an `ignored_reason`.
- Improve `pcl code search`: match multi-term queries at file level (terms
  may be on different lines), and rank results by relevance — symbol
  definition hits above prose mentions, source above docs for code-shaped
  queries — with deterministic tie-breaking. Document the ranking.
- Improve Python test hints with stdlib `ast` import analysis: a test file
  importing (directly or via `pcl.<module>`) a changed module is a hint,
  in addition to filename matching.
- Ship a realistic eval fixture derived from this repo's actual history
  (tasks 0068/0069/0070 changes with labeled expected files/tests) into
  `tests/fixtures/`, and assert in a test that overall precision and recall
  on it meet or exceed a recorded floor that is better than the 2026-07-05
  baseline (precision 0.1429 / recall 0.6667). Record before/after metrics
  in the final report.

## Acceptance Criteria

- Real historical diffs from this repo parse with zero content-line paths.
- On the realistic fixture, precision and recall improve over the recorded
  baseline, and the test suite enforces the new floor.
- `pcl impact --diff` on this repo with a single-module source change
  returns a bounded, reasoned `likely_impacted` list; nothing at
  confidence 0.5 justified only by a repo-ubiquitous phrase.
- `pcl code search "token estimator" --json` ranks `src/pcl/context.py`
  and `tests/test_context.py` above prose mentions in README/agent-tasks.
- Session/state noise paths are excluded by default and the exclusion is
  overridable and documented.
- Receipts still validate against `context-receipt/v0`; additive contract
  evolution only.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init` smoke
  against a temp directory passes.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not add embeddings, Tree-sitter, call graphs, or semantic retrieval.
- Do not bump contract versions; evolve `impact/v0`, `code-search/v0`,
  `code-index/v0`, and `context-receipt/v0` additively.
- Do not add daemons or file watchers.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not read or parse generated dashboard HTML.
- Do not add hosted services, telemetry, paid services, or plugin
  distribution.
