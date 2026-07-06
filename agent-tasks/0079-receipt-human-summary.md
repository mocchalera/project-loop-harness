# Task 0079: Receipt Human Summary (`pcl receipt show`)

## Goal

Give humans (and agents that want a compact view) a fast, readable
rendering of a context receipt. A power user must be able to answer, in
under 30 seconds: what changed, what is likely impacted, what was
omitted, what is stale, what is untracked-and-missing, and what to
verify next.

This task builds ON TOP of the shared summary model shipped in 0078
(`code-context-summary/v0`, `src/pcl/code_context/summary.py`,
`summarize_code_context_receipt`). It must NOT re-implement summary
construction.

## Design constraints (agreed, do not relitigate)

- Summary generation logic is the 0078 shared model. `receipt show`
  adds resolution (id/path → receipt payload) and rendering only.
- No `safe_to_continue` or any go/no-go verdict. Facts and warnings
  only; judgment stays with verification / escalation / human decision.
- Wording: "included as candidate context" / "omitted"; never
  "understood", "read", "analyzed".
- The human renderer must be a reusable pure function (summary dict →
  markdown/text) so the dashboard can later render the same Context
  Receipt Summary card from the same model. Do not wire the dashboard
  in this task.
- No new runtime dependencies, no schema migration, no contract
  version bumps.

## Scope

### 1. `pcl receipt show <ref>`

- New top-level `receipt` command group with a `show` subcommand.
- `<ref>` accepts either:
  - an evidence id (e.g. `E-0001`) — resolved via the evidence table
    (`type = "context_receipt"`), or
  - a receipt path (absolute, or relative to the project root, e.g.
    `.project-loop/evidence/context-receipts/e-0001-impact-v0.json`).
- Optional `--latest` convenience: with no `<ref>`, resolve the most
  recent `context_receipt` evidence row (same resolution logic 0078
  uses for `--include-code-context`; extract/share the helper rather
  than duplicating it).
- Load the receipt JSON, build the summary via
  `summarize_code_context_receipt`, then render.

### 2. Output modes

- Default: human-readable text/markdown, rendered by a pure function
  (e.g. `render_receipt_summary(summary) -> str`) in
  `src/pcl/code_context/summary.py` or a sibling module.
- Ordered for 30-second triage; changed / impacted / omitted / stale /
  untracked / verification are visually separated:
  1. Receipt ref (evidence id, path, created_at) and diff source /
     base ref
  2. Counts line: changed / excluded changed / sensitive omitted
  3. Staleness warnings (verbatim, each on its own line)
  4. Untracked omission warning
  5. Included candidate context top N (path, role, reason,
     snapshot_consistency) plus `included_total`
  6. Omitted reason counts
  7. Verification suggestions
  8. Next recommended command (reuse the summary's guidance fields;
     e.g. refresh index when stale, `pcl impact --diff` when the
     receipt is old)
- `--json`: print the `code-context-summary/v0` payload (the shared
  model output, not a new shape).

### 3. Error handling

- Unknown evidence id, non-receipt evidence id, missing file, invalid
  JSON, or wrong contract version → typed errors (existing error
  classes / exit-code conventions) with a next-action suggestion, not a
  stack trace.
- No receipts exist at all with `--latest` → same next-action guidance
  the 0078 no-receipt path uses (`pcl index build`, then
  `pcl impact --diff`).

### 4. Documentation

- `docs/code-context.md`: document `pcl receipt show` (ref forms,
  `--latest`, `--json`), with a sample human rendering, and state that
  the human view and the pack `code_context` section derive from the
  same `code-context-summary/v0` model.

## Acceptance Criteria

- `pcl receipt show E-XXXX`, `pcl receipt show <path>`, and
  `pcl receipt show --latest` all work against a real project fixture.
- Summary construction calls `summarize_code_context_receipt`; there is
  no duplicated summary-building code (a test may assert the JSON
  output equals the shared model output for the same receipt).
- `--json` contract is fixed by a golden test on a stable fixture
  receipt.
- Human output contains the sections in the order above; a test asserts
  presence and ordering of the key headings/labels.
- Wording test: rendered output never contains "understood",
  "analyzed"; candidate lines use "candidate context" phrasing.
- No `safe_to_continue`-like field or verdict line in either mode.
- Error cases (bad id, bad path, invalid JSON, empty project) produce
  typed errors with guidance; tests cover each.
- `ruff check .` passes; full `python3 -m pytest` passes (350 currently
  green, plus new tests); `pcl init` smoke against a temp dir passes.
- No new runtime dependency, no schema migration.

## Do Not

- Do not re-implement or fork the summary model; extend
  `code-context-summary/v0` additively only if a rendering need
  genuinely requires it (and then update 0078's tests accordingly).
- Do not add `safe_to_continue` or any go/no-go verdict.
- Do not wire the dashboard/HTML renderer in this task; only keep the
  render function reusable.
- Do not read or parse generated dashboard HTML.
- Do not add embeddings, Tree-sitter, call graphs, or semantic
  retrieval.
- Do not use raw SQL to mutate `.project-loop/project.db`; read-only
  evidence lookups use the existing db helpers.
- Do not add hosted services, telemetry, or new runtime dependencies.
