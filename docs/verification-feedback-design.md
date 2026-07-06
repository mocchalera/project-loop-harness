# v0.2.x Design: Measurement and Feedback (Milestone 12)

Status: **APPROVED 2026-07-06 (human approval, with refinements
below).** Migration 005 is approved under
`require_human_approval: database_migration`. Implementation starts
after the v0.1.12 Bridge Reliability release; task 0087 may start
immediately after it.

Scope: Milestone 12 in `docs/implementation-plan.md` (retrieval eval
suite hardening + verification suggestion feedback loop), plus the
approved scope amendment (dogfood-to-fixture workflow).

## Why this milestone exists

Two purposes, in priority order:

1. **Investment gating.** The semantic promotion gate says embeddings /
   Tree-sitter / call graphs stay out until the eval suite shows
   missing-critical-context failing to improve under lexical tuning.
   That gate is only meaningful if the eval suite is trustworthy and
   fed by real usage.
2. **Closing the suggestion loop.** v0.1.11 delivers verification
   suggestions into context packs; today they are advice with no
   record of whether anyone acted on them. Without executed/skipped
   visibility, PLH cannot evaluate its own suggestions.

An eval whose fixtures do not grow from dogfood examples is not
credible. That is why the dogfood-to-fixture workflow is in scope and
sequenced BEFORE baseline record/compare.

## Part 1: Verification suggestion IDs (approved)

### Current state

`context-receipt/v0` carries `verification_suggestions` as a plain
list of strings (`receipts.py` → `_receipt_payload`;
`summary.py` passes them through with `_string_list`). Nothing can
reference an individual suggestion.

### Design

Evolve the receipt payload (receipt contract is v0/unstable; the
`code-context-summary/v0` isolation layer shields `context-pack/v1`
consumers — this is exactly what the isolation layer was built for):

```json
"verification_suggestions": [
  {
    "id": "E-0001/VS-01",
    "command": "python3 -m pytest tests/test_context.py",
    "reason": "test_hint:path_token_match"
  }
]
```

- **ID scheme (approved)**: `<receipt evidence_id>/VS-<nn>`,
  deterministic within a receipt, ordinal by position. No new DB
  sequence, no migration needed for minting, and the receipt
  reference is embedded in the ID itself.
- **No `status` field in the receipt (approved refinement).** A
  receipt is an immutable candidate presentation; suggestion state
  lives exclusively in the `verification_feedback` table. Nothing in
  the receipt or summary implies a lifecycle.
- `summary.py` and `pcl receipt show` render `command` (display is
  unchanged for humans) and carry `id` in the JSON summary.
- Backward compatibility: `summarize_code_context_receipt` accepts
  both string-list (old receipts on disk) and object-list forms; old
  receipts summarize as objects with `id: null`.

## Part 2: Verification feedback recording (approved — Option A)

### Storage: migration 005, append-only event table

**Approved with the refinement that this is an append-only feedback
EVENT table, not a current-state table.** Multiple feedback rows per
suggestion are allowed by design; there is deliberately NO
`UNIQUE(suggestion_id)`. "Latest feedback" and "no feedback recorded"
are derived at read time, never stored.

```sql
CREATE TABLE IF NOT EXISTS verification_feedback (
  id TEXT PRIMARY KEY,
  suggestion_id TEXT NOT NULL,
  receipt_evidence_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('executed', 'skipped', 'not_applicable')),
  result TEXT CHECK(result IN ('passed', 'failed', 'inconclusive')),
  supporting_evidence_id TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  CHECK(
    (status = 'executed' AND result IS NOT NULL AND supporting_evidence_id IS NOT NULL)
    OR (status != 'executed' AND result IS NULL)
  ),
  FOREIGN KEY(receipt_evidence_id) REFERENCES evidence(id),
  FOREIGN KEY(supporting_evidence_id) REFERENCES evidence(id)
);
```

Approved field semantics:

- `executed` REQUIRES `result` and `supporting_evidence_id`.
- `skipped` / `not_applicable` carry `result: NULL`.
- There is NO `never_seen` status: PLH cannot observe non-observation.
  A suggestion with zero feedback rows is displayed as "no feedback
  recorded" — a derived state, not a stored claim.

Recording is CLI-only (never raw SQL):

```bash
pcl verify feedback --suggestion E-0001/VS-01 --status executed \
  --result passed --evidence E-0009
```

- **Referential honesty (approved refinement):** `pcl verify feedback`
  loads the receipt referenced by the suggestion ID prefix and
  verifies the suggestion ID actually exists in that receipt's
  payload before recording; unknown IDs are a typed error.
- Every insert also appends a JSONL event (standard audit trail).

Epistemic boundary (same discipline as receipts): `executed` +
`result` are claims by the caller recording the feedback, backed by
the referenced evidence artifact. PLH does not verify the command was
actually run; it stores the claim and its evidence pointer. Vocabulary
must not drift into "verified safe".

### Metric vocabulary (approved refinement)

v0.2.0 exposes ONLY observable rates; suggestion usefulness is NOT a
v0.2.0 metric:

- `execution_rate`: suggestions with ≥1 `executed` feedback / total
  suggestions with any feedback opportunity window (definition fixed
  in the task spec).
- `executed_pass_rate` / `executed_fail_rate`: over `executed`
  feedback events.
- `feedback_coverage_rate`: suggestions with ≥1 feedback row of any
  status / total suggestions issued.

Do NOT call `passed`/`failed` "hit"/"miss". `passed` does not mean the
suggestion was useless (a passing suggested test can still have been
worth running). Usefulness judgments are a later, optional human
labeling layer, not a computed v0.2 metric.

## Part 3: Eval baseline history and regression gate (approved)

- `pcl eval retrieval --record-baseline`: stores the eval result as
  evidence (JSON artifact under
  `.project-loop/evidence/retrieval-eval/`) plus an event.
- Baseline artifact provenance (approved refinement — all fields
  required): fixture path + fixture content hash, target repo git
  HEAD, index run id + index detail hash, code_context config hash
  (the effective `code_index` config subtree), `pcl` version, and
  eval contract version (`retrieval-eval/v0`).
- `pcl eval retrieval --compare-baseline`: compares current metrics to
  the latest recorded baseline for the same fixture hash; reports
  per-metric deltas.
- Gate policy (approved):
  - Metric thresholds (precision / recall / missing-critical-context /
    false-positive / token-cost) stay ADVISORY until the 5-kind
    fixture set exists and observed variance across baseline history
    justifies thresholds.
  - Eval INFRASTRUCTURE integrity failures ARE blocking: schema
    corruption, eval command failure, fixture contract violations.
    Broken measurement is not advisory.
- Metrics per fixture kind (code change, docs-only, config-only,
  rename/move, secret omission): precision, recall,
  missing-critical-context rate, false-positive rate, token cost
  (estimated tokens of included candidate context).

## Part 4: Dogfood-to-fixture (approved scope amendment)

- `pcl eval fixture propose --from-receipt <evidence-id>`: generates a
  `retrieval-fixture/v0` candidate from a real receipt — changed
  files, retrieved candidates, and EMPTY `expected_files` /
  `expected_tests` / `critical_context` blocks plus
  `labels_status: "unlabeled"`.
- **PLH never fabricates ground-truth labels (approved refinement).**
  The proposed fixture must be visibly unlabeled; filling the expected
  blocks is a human review step by definition.
- Candidates land in a staging area (`fixtures/proposed/`); adoption
  into `tests/fixtures/` is a manual move after human labeling. No
  auto-adoption path exists.

## Explicitly out of scope for v0.2.x

Unchanged from the promotion gate: embeddings, Tree-sitter
requirement, call graphs, semantic retrieval, hosted search,
content-based secret scanning, automatic go/no-go verdicts. Also out:
automatic execution of suggested verification commands (recording is
manual/CLI-driven; auto-execution is a different trust conversation),
and computed "suggestion usefulness" metrics (optional human labels
come later).

## Sequencing (approved order)

1. **0087**: suggestion IDs + summary/show compatibility — no
   migration; may start immediately after v0.1.12.
2. **0088**: migration 005 (`verification_feedback` append-only event
   table) + `pcl verify feedback` with in-receipt suggestion ID
   validation + observable-rate metrics.
3. **0089**: dogfood-to-fixture propose command (staging area,
   unlabeled candidates) — deliberately BEFORE baseline work so
   baseline history grows over a fixture set that is already being
   fed by dogfood.
4. **0090**: baseline record/compare with full provenance + CI
   advisory comparison (infrastructure failures blocking, metric
   thresholds advisory).

## Approval record

Approved 2026-07-06 with the following refinements, all incorporated
above:

1. Option A confirmed; table is append-only event log, no
   `UNIQUE(suggestion_id)`; `executed` requires `result` +
   `supporting_evidence_id`; no `never_seen` status (derived display
   only).
2. Dogfood-to-fixture officially added to Milestone 12; staging-only,
   human-labeled, sequenced before baseline record/compare.
3. Advisory-first gate confirmed; eval infrastructure integrity
   failures may block; baseline artifacts carry full provenance
   (fixture hash, git HEAD, index run/detail hash, code_context
   config hash, pcl version, eval contract version).
4. `E-xxxx/VS-nn` ID scheme confirmed; no `status` field in receipt
   payloads (receipts are immutable candidate presentations; state
   lives in `verification_feedback`); `pcl verify feedback` validates
   suggestion existence in the referenced receipt.
5. Metric vocabulary limited to observable rates (`execution_rate`,
   `executed_pass_rate`, `executed_fail_rate`,
   `feedback_coverage_rate`); no hit/miss framing; usefulness is a
   future optional human label.
