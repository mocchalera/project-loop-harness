# Task 0082: Receipt Relevance + Age Label (P1)

## Goal

`pcl context pack --include-code-context` embeds the LATEST
`context_receipt` evidence (`latest_context_receipt_ref` is a plain
`ORDER BY created_at DESC LIMIT 1`). The receipt may have nothing to do
with the pack's target task/job, and it may be hours old. Nothing in
the pack says so. An agent reading the pack can mistake an unrelated or
stale diff for current-task context — the exact "plausible but wrong
context" failure a control plane must not cause.

Label the facts: how the receipt was selected (scope), how strongly it
is bound to the pack target (binding strength), and how old it is
(age). These are honest selection/freshness facts, NOT a relevance
judgment — PLH does not claim the receipt is or is not related to the
target.

## Design constraints (agreed, do not relitigate)

- Vocabulary is deliberately weak and factual. `scope` describes the
  SELECTION METHOD, `binding_strength` describes who asserted the
  target linkage. In v0.1.12 the only shipping values are:
  - `scope: "unscoped_latest"` (receipt selected by recency) and
    `scope: "missing_receipt"` (no receipt exists).
  - `binding_strength: "none"` (nobody asserted a linkage).
- `target_bound` / `binding_strength: "caller_asserted"` are FUTURE
  values (a `--for-task` flag would record a caller-asserted label,
  never a PLH-verified semantic relation). Document them as reserved;
  do NOT implement the flag in this task.
- Relevance and age are stamped at the PACK layer (which knows the
  selection method and the pack target), not inside the pure
  `summarize_code_context_receipt` receipt→summary function. Shared
  helpers may live in `summary.py` but must stay pure (age computation
  takes `now` as a parameter for determinism/testability).
- No schema migration, no new runtime dependency, additive
  `code-context-summary/v0` / `context-pack/v1` evolution only.
- No `safe_to_continue`, no go/no-go, no relevance scoring.

## Scope

### 1. `code_context.relevance`

Added to the embedded `code_context` object for both job and task
packs:

```json
"relevance": {
  "target_type": "task",
  "target_id": "T-0100",
  "scope": "unscoped_latest",
  "binding_strength": "none",
  "reason": "The most recent context receipt was selected by recency; it was not created for this target."
}
```

- `target_type` / `target_id` mirror the pack `target`.
- When no receipt exists (`status: "missing_receipt"`), relevance is
  present with `scope: "missing_receipt"`, `binding_strength: "none"`,
  and a reason saying no receipt was available.
- When the receipt exists but is unreadable (`status:
  "unavailable"`), keep the existing unavailable summary and stamp
  relevance with `scope: "unscoped_latest"` plus the existing
  unavailable reason handling (the selection method was still
  recency).

### 2. `code_context.receipt_age` and `age_warning`

- `receipt_age`: `{"created_at": <receipt created_at>,
  "age_seconds": <int >= 0>}` computed against `timeutil.utc_now_iso`
  time at pack build (inject `now` in the helper signature; tests pass
  a fixed value).
- If `created_at` is missing or unparsable: `receipt_age` carries
  `created_at` only, and `age_warning` states the age could not be
  computed.
- `age_warning` (sibling string field, absent when not warranted):
  present when `age_seconds > 3600`. The 3600s threshold is a named
  constant, documented as provisional pending dogfood data — do not
  make it configurable yet.

### 3. Render into the safety section

- The `code_context_safety` pack section (required per 0083) gains
  short factual lines, e.g.:
  - `- relevance: unscoped_latest (binding: none) — latest receipt,
    not created for this target`
  - `- receipt age: 5400s (created_at 2026-07-06T00:00:00Z)` plus the
    warning line when `age_warning` is set.
- `pcl receipt show` renders `receipt_age` / `age_warning` when
  present (same shared helper); it does NOT render `relevance`
  (receipt show has no pack target).

### 4. Documentation

- `docs/context-pack.md`: document `relevance` (including the
  reserved future values and the explicit statement that
  `caller_asserted` would be a caller label, not a PLH-verified
  relation), `receipt_age`, `age_warning`, and the provisional
  threshold.

## Acceptance Criteria

- Job pack and task pack with `--include-code-context`: `relevance`
  present with correct `target_type`/`target_id`,
  `scope: "unscoped_latest"`, `binding_strength: "none"`.
- Missing-receipt case: `scope: "missing_receipt"` and the safety
  section says no receipt was available.
- Age: fixed-`now` tests for fresh (< threshold, no warning), stale
  (> threshold, warning present in JSON AND in the rendered safety
  section), and unparsable `created_at` (warning about uncomputable
  age).
- The safety-section relevance/age lines survive tight budgets by
  virtue of 0083's required-section invariant (add one integration
  test: small budget, safety section present, relevance line in
  body).
- `pcl receipt show` output includes age for a receipt with
  `created_at`, and never includes a `relevance` block.
- Determinism: no direct wall-clock reads inside summary helpers;
  `now` is parameterized end-to-end below the CLI boundary.
- Existing packs without `--include-code-context` are byte-stable.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not implement `--for-task` / `--for-job` / `--require-bound-receipt`
  (future work; vocabulary reserved in docs only).
- Do not compute or imply semantic relatedness between the receipt
  and the target (no scores, no "related: yes/no").
- Do not add `safe_to_continue` or any go/no-go field.
- Do not make the age threshold configurable yet.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
