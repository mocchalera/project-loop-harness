# Task 0078: Context Pack × Code Context Bridge (with isolation layer)

## Goal

Connect the two planes that are currently separate: `pcl context pack`
(agent handoff, stable `context-pack/v1` contract) and the Code Context
receipt (`context-receipt/v0`, still evolving). An agent reading a
context pack must be able to see what changed, what was excluded, what
was omitted as sensitive, what is stale, what is untracked-and-missing,
and what to verify — without the pack contract inheriting instability
from the receipt contract.

The bridge is NOT "embed the receipt into the pack". It is a shared
summary model that isolates the two contracts.

## Design constraints (agreed, do not relitigate)

- `context-pack/v1` is a stable contract; `context-receipt/v0` is
  evolving. A **shared receipt summary model** (`code-context-summary/v0`)
  sits between them as an isolation layer.
- The pack embeds ONLY the summary. The receipt body is referenced via
  `evidence_id` / `receipt_path`, never inlined.
- No `safe_to_continue` or any go/no-go field. PLH reports facts and
  warnings (staleness, sensitive omission, excluded changed files,
  untracked omission); judgment stays with existing
  verification / escalation / human decision flows.
- No new runtime dependencies, no schema migration, no contract version
  bump for `context-pack/v1` (additive optional section only).

## Scope

### 1. Shared receipt summary model (`code-context-summary/v0`)

- New module in `src/pcl/code_context/` (e.g. `summary.py`).
- A pure function: receipt payload dict → summary dict. No I/O in the
  transform itself; a small loader helper may resolve
  latest-receipt-by-evidence lookup.
- Summary fields (derive from `context-receipt/v0` payload produced by
  `receipts._receipt_payload`):
  - `contract_version`: `"code-context-summary/v0"`
  - `receipt_ref`: `{evidence_id, receipt_path, created_at}`
  - `diff_source`, `base_ref` (when present)
  - `index_run`: id + created_at only
  - `changed_file_count`, `excluded_changed_file_count`
  - `sensitive_omitted_count`
  - `staleness_warnings` (full list, never truncated)
  - `untracked_omission_warning`: fixed factual sentence stating that
    untracked files are NOT included in this receipt (git-diff based
    modes only report tracked files)
  - `included_candidate_context_top`: top N (default 10) paths with
    reason/score fields as available; include `included_total`
  - `omitted_reason_counts`: aggregated counts by reason
  - `verification_suggestions` (full list)
  - `sensitive_include_override_used` when the underlying index run
    recorded it (surface the existing audit signal from
    `store.py` run summary)
- Wording rule: summaries say files were "included as candidate
  context" / "omitted"; never "understood", "read", "analyzed".
- The function must tolerate additive evolution of
  `context-receipt/v0`: unknown receipt fields are ignored; missing
  optional fields degrade to explicit defaults, not KeyError.

### 2. `pcl context pack --include-code-context`

- New optional flag on `pcl context pack` (both `--job` and `--task`
  targets).
- Resolves the most recent `context_receipt` evidence row (the evidence
  table already stores `type = "context_receipt"` with the receipt
  path); loads the receipt JSON; builds the summary via the shared
  model.
- Adds an optional `code_context` section to the pack markdown and to
  the JSON payload. Contract stays `context-pack/v1`; the section is a
  documented additive extension. Existing packs without the flag are
  byte-identical to today.
- Non-droppable safety facts: register the safety subset
  (diff_source, receipt_ref, sensitive_omitted_count,
  staleness_warnings, excluded_changed_file_count,
  untracked_omission_warning) using the EXISTING section priority
  mechanism in `src/pcl/context.py` — the same pinned-priority pattern
  used for `machine_context_rules` (priority 10000). Do not build a new
  budget mechanism. The verbose parts (candidate context top N,
  verification suggestions) may be budget-droppable like normal
  sections.
- Role profiles: for a verifier-type role, verification_suggestions get
  higher priority than candidate context listing.
- No receipt exists → the pack does not fail; the `code_context`
  section states no receipt is available and suggests the next action
  (`pcl index build`, then `pcl impact --diff`).
- Receipt exists but index/staleness warnings present → warnings appear
  verbatim in the non-droppable subset.

### 3. Documentation

- `docs/context-pack.md`: document the optional section, the isolation
  layer rationale (receipt v0 evolves; pack v1 stays stable; summary
  model absorbs the drift), and the non-droppable guarantee list.
- `docs/code-context.md`: document `code-context-summary/v0` and state
  explicitly: PLH is not a secret scanner; sensitive omission is
  path/pattern based (`code_index.sensitive_exclude`,
  `sensitive_include_override` with audit trail); content-based
  detection is out of scope.

## Acceptance Criteria

- `code-context-summary/v0` exists as a pure function with direct unit
  tests, including: a receipt with extra unknown fields produces a valid
  summary (isolation property); a receipt missing optional fields
  produces explicit defaults.
- `pcl context pack --job <id> --include-code-context --json` succeeds
  and contains a `code_context` section whose content is ONLY the
  summary (assert no `included_candidate_context` full array, no
  `omitted` full array from the receipt body).
- `evidence_id` and `receipt_path` references are present.
- With an artificially tiny `--max-tokens`, sensitive_omitted_count,
  staleness_warnings, excluded_changed_file_count, diff_source,
  untracked_omission_warning, and receipt_ref survive in the rendered
  pack while droppable sections are omitted.
- No `safe_to_continue`-like field anywhere in summary or pack.
- Packs built WITHOUT the flag are unchanged (golden/regression test).
- No-receipt case returns a next-action suggestion, not an error.
- Wording check: no "understood/analyzed/read" phrasing in summary
  output (test may assert on the strings used).
- `ruff check .` passes; full `python3 -m pytest` passes (341 currently
  green, plus new tests); `pcl init` smoke against a temp dir passes.
- No new runtime dependency, no schema migration, no version bump of
  `context-pack/v1` or `context-receipt/v0`.

## Do Not

- Do not inline the receipt body into the pack.
- Do not add `safe_to_continue` or any go/no-go verdict field.
- Do not build a new token-budget or priority mechanism; reuse the
  existing section priority machinery in `src/pcl/context.py`.
- Do not implement `--staged` / `--unstaged` / `--include-untracked`
  diff modes here (that is task 0081); this task only adds the factual
  untracked omission warning.
- Do not add content-based secret detection (explicitly out of scope;
  document it instead).
- Do not add embeddings, Tree-sitter, call graphs, or semantic
  retrieval.
- Do not use raw SQL to mutate `.project-loop/project.db` from agents;
  implementation code uses the existing store/evidence helpers.
- Do not add hosted services, telemetry, or new runtime dependencies.
