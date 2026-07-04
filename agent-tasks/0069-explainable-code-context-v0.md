# Task 0069: Explainable Code Context v0

## Goal

Give the control plane a minimal, dependency-free codebase index so context
handoffs can carry auditable code context: what was provided as candidate
context, why, what was omitted, how stale the index is, and what verification
is suggested.

Direction (approved 2026-07-04): PLH does not compete with IDE-grade search
engines, but it must own the minimum codebase intelligence needed to generate
and later verify auditable context receipts. Receipts without an index are
self-reported logs; an index without receipts is a commodity feature.

## Scope

- Add migration 004 (approved) with exactly two tables:
  - `code_index_runs`: id, root_path, created_at, git_head, file_count,
    indexed_bytes, ignored_count, index_version, status, summary_json.
  - `code_index_files`: id, index_run_id, path, language, size_bytes, mtime,
    sha256, line_count, symbol_summary_json, test_hint_json.
- `pcl index build --json` and `pcl index status --json`: gitignore-aware
  file map with hash, mtime, size, language detection, and ignore rules
  (`.project-loop`, `.venv`, `node_modules`, `dist`, binaries, large files).
  Excluded files record an `ignored_reason`; sha256 is skipped for large or
  binary files with the reason recorded.
- `pcl code search "<query>" --json`: stdlib-only lexical search returning
  path, lines, snippet, and reason.
- Symbol-lite extraction into `symbol_summary_json`: Python `def`/`class`,
  JS/TS `function`/`class`/`export`, Markdown headings.
- Test-hint heuristic into `test_hint_json`: map source files to candidate
  test files by filename and import conventions.
- `pcl impact --diff --json` with contract version `impact/v0`: changed files
  versus the index, `likely_impacted` entries with reason and confidence,
  `verification_suggestions`, `omitted`, `staleness_warnings`, and
  `receipt_path`.
- Context receipt JSON artifact written under
  `.project-loop/evidence/context-receipts/` and registered through the
  existing evidence mechanism (no new table). Field vocabulary must be
  epistemically honest: `included_candidate_context`, `omitted`,
  `staleness_warnings`. The receipt must never claim an agent "read" or
  "understood" anything; it records what PLH provided and why.
- Retrieval evaluation: a fixture format for labeled tasks (expected files,
  expected tests) plus `pcl eval retrieval --fixture <path> --json` reporting
  precision, recall, and missing-critical-context against the labels.
- Documentation: new contract doc for index/impact/receipt, data-model
  update, README surface update.

## Acceptance Criteria

- `pcl index build --json` over the same tree is deterministic and updates
  `code_index_runs` and `code_index_files`; failures exit with typed errors
  and do not leave partial state.
- `pcl index status --json` reports stale, file_count, ignored_count, and
  last run.
- Index runs append events to `events.jsonl`.
- `pcl impact --diff --json` returns an `impact/v0` document and writes a
  receipt artifact registered as evidence.
- `pcl eval retrieval` produces precision/recall/missing metrics from a
  fixture checked into `tests/`.
- `ruff check .` passes.
- Full `python3 -m pytest` passes.
- `pcl init` smoke flow against a temp directory passes.
- Runtime dependencies stay empty (stdlib only).

## Do Not

- Do not add embeddings, Tree-sitter, call graphs, or semantic retrieval
  (deferred to v2; promotion requires missing-critical-context evidence from
  `pcl eval retrieval`).
- Do not add daemons or file watchers; indexing is explicit.
- Do not treat the index as a source of truth for code — the git working
  tree remains truth; the index is a snapshot with staleness detection.
- Do not access the network.
- Do not read or parse generated dashboard HTML.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, paid services, or plugin
  distribution.

## Sequencing

Land after task 0068: both touch `src/pcl/context.py`, and the token
estimator must be stable before receipts report budgets.

Deferred to v1 (recorded, not in scope): `retrieval_queries` /
`retrieval_results` tables, `agent-output` v1.1 `files_consulted` reporting,
and `pcl receipt verify` (claimed-versus-verified hash checks).
