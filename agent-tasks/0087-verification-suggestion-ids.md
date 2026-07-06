# Task 0087: Verification Suggestion IDs

Design source: `docs/verification-feedback-design.md` Part 1
(approved 2026-07-06). Read it before implementing. Where this spec
and the design doc disagree, the design doc wins.

## Goal

`context-receipt/v0` currently carries `verification_suggestions` as a
plain list of strings. Nothing can reference an individual suggestion,
so no feedback can ever be recorded against one. Move suggestions to
an object list with deterministic per-receipt IDs, without breaking
consumers of old receipts on disk.

## Design constraints (approved, do not relitigate)

- ID scheme: `<receipt evidence_id>/VS-<nn>`, e.g. `E-0001/VS-01`.
  Deterministic within a receipt, ordinal by position (01-based,
  zero-padded to two digits). No new DB sequence, no migration.
- SUGGESTION OBJECTS get no `status`/`state`/lifecycle field and no
  lifecycle vocabulary: each object carries exactly `id`, `command`,
  `reason`. A receipt is an immutable candidate presentation;
  suggestion state will live exclusively in the
  `verification_feedback` table (task 0088).
  **Clarified 2026-07-06 after first acceptance pass:** this rule is
  scoped to verification suggestions only. It does NOT touch other
  recorded facts that happen to use the word "status" — in
  particular `changed_files[].status` / `excluded_changed_files[].status`
  (git change status) in receipts, and the summary's availability
  `status` (`from_receipt` / `missing_receipt` / `receipt_unavailable`)
  must be preserved unchanged. The first implementation applied the
  rule as a recursive key strip and broke both; do not repeat that.
- The receipt contract is v0/unstable; the `code-context-summary/v0`
  isolation layer shields `context-pack/v1` consumers. The summary
  contract change here is additive only (`id` per suggestion).

## Scope

### 1. Receipt payload (`src/pcl/code_context/receipts.py`)

- `verification_suggestions` becomes a list of objects:
  `{"id": "E-xxxx/VS-01", "command": "...", "reason": "..."}`.
- `reason` carries the existing suggestion provenance (e.g.
  `test_hint:path_token_match`); if current code has no reason
  string, derive it from the existing suggestion source and keep it
  short and mechanical — no invented rationale text.

### 2. Summary compatibility (`src/pcl/code_context/summary.py`)

- `summarize_code_context_receipt` accepts BOTH forms:
  - object list (new receipts): pass through `id`, `command`,
    `reason`;
  - string list (old receipts on disk): summarize as objects with
    `id: null` and `command` set to the string.
- The JSON summary includes `id` for each suggestion.

### 3. Human display

- `pcl receipt show` and the context pack code-context section keep
  rendering the command text as today; the ID may be appended in an
  unobtrusive way (e.g. trailing `[E-0001/VS-01]`) but the display
  must not become ID-first. Old receipts render without IDs, no
  placeholder noise.

### 4. Documentation

- `docs/code-context.md`: new suggestion object shape, ID scheme,
  determinism, and the no-status rule.
- `docs/context-pack.md`: note the additive summary field.

## Acceptance Criteria

- Same receipt input → same suggestion IDs (explicit determinism
  test).
- Old string-list receipt fixture summarizes with `id: null` and
  renders through `pcl receipt show` and
  `pcl context pack --include-code-context` without error. Keep a
  permanent old-form fixture under `tests/fixtures/`.
- New receipts written by `pcl impact --diff` carry object-form
  suggestions with sequential IDs.
- Suggestion objects carry exactly `{id, command, reason}` in
  receipts, and only `id`/`command`/`reason` in summaries (assert in
  a test). Assert also that `changed_files[].status` in a fresh
  receipt and the summary availability `status` field are PRESERVED —
  the no-lifecycle rule is scoped to suggestions, not a global key
  ban.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not add a migration or touch the DB schema.
- Do not mint IDs from timestamps, randomness, or a DB sequence.
- Do not change which suggestions are generated or their order.
- Do not use hit/miss/usefulness vocabulary anywhere.
- Do not use raw SQL against `.project-loop/project.db`.
