# Task 0089: Dogfood-to-Fixture Propose (v0.2.1)

Design source: `docs/verification-feedback-design.md` Part 4 plus the
Approval addendum item 4 (staging location). Where this spec and the
design doc disagree, the design doc wins. No migration, no new
runtime dependency.

## Goal

An eval suite whose fixtures do not grow from real usage is not
credible. Add `pcl eval fixture propose --from-receipt <evidence-id>`
so real context receipts become UNLABELED fixture candidates that a
human labels before adoption. PLH never fabricates ground-truth
labels.

## Design constraints (approved, do not relitigate)

- Staging area is repo-root `fixtures/proposed/` — a reviewable,
  Git-tracked source asset, NOT `.project-loop/` state.
- Proposed candidates carry `labels_status: "unlabeled"` and EMPTY
  `expected_files` / `expected_tests` / `critical_context` arrays.
  Filling them is a human review step by definition.
- Adoption into `tests/fixtures/` is a manual `git mv`-style step
  after human labeling. NO auto-adoption path exists, and none may
  be added.

## Scope

### 1. `pcl eval fixture propose --from-receipt <evidence-id> [--json]`

- Loads the referenced evidence row; it must be `type =
  'context_receipt'` with a readable `context-receipt/v0` artifact —
  unknown evidence, wrong type, or unreadable artifact are distinct
  typed errors (reuse the receipt-loading discipline from
  `verification_feedback.py` where sensible).
- Emits `fixtures/proposed/<receipt-evidence-id>-retrieval.json`
  (lowercased evidence id, deterministic name; refuse to overwrite an
  existing file unless `--force` — overwriting a half-labeled
  candidate silently would destroy human work).
- Candidate shape: `retrieval-fixture/v0` with ONE task:
  - `id`: derived from the receipt evidence id (deterministic).
  - `diff`: a minimal synthetic unified diff touching exactly the
    receipt's `changed_files` paths (same mechanical style as
    existing fixtures). Receipts do not store original diff text, so
    the replay diff is synthesized; record that honestly via
    `diff_synthesized_from_receipt: true` inside the task.
  - `expected_files: []`, `expected_tests: []`,
    `critical_context: []`, `labels_status: "unlabeled"`.
  - `source_receipt` provenance block: `evidence_id`, `created_at`,
    `diff_source`, `base_ref` (when present), and
    `retrieved_candidate_paths` (the receipt's
    `included_candidate_context` paths) — this is the raw material
    the human labeler starts from, clearly provenance, not labels.
- Append one JSONL event (`eval_fixture_proposed`) recording the
  receipt evidence id and output path. No SQLite mutation.

### 2. Guard: eval refuses unlabeled fixtures

- `pcl eval retrieval` on a fixture whose tasks carry
  `labels_status: "unlabeled"` (or empty expected+critical blocks
  alongside that marker) fails with a typed error telling the
  operator to label the candidate and move it into `tests/fixtures/`.
  Labeled/legacy fixtures (no `labels_status` field) evaluate as
  today.

### 3. Documentation

- `docs/code-context.md` (eval section): propose workflow, staging
  directory, human labeling step, manual adoption, and the
  no-fabricated-labels rule.
- Add `fixtures/proposed/.gitkeep` (or a one-line README.md in that
  directory) so the staging area exists in Git.

## Acceptance Criteria

- Proposing from a real receipt fixture yields a candidate that is
  byte-deterministic given the same receipt (no timestamps of its
  own — reuse the receipt's `created_at`).
- Candidate visibly unlabeled: `labels_status: "unlabeled"`, all
  three expected/critical arrays empty (contract test).
- `pcl eval retrieval` against the proposed candidate → typed error;
  after a test labels it (filling expected blocks, removing/flipping
  `labels_status`), evaluation runs and produces metrics.
- Unknown/wrong-type/unreadable receipt → distinct typed errors,
  nothing written.
- Existing candidate without `--force` → typed error, file untouched.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not fill or guess expected/critical labels from receipt data.
- Do not add an auto-adoption or auto-labeling path.
- Do not write candidates anywhere under `.project-loop/`.
- Do not mutate SQLite; the only side effects are the candidate file
  and one JSONL event.
- Do not use hit/miss/usefulness vocabulary.
