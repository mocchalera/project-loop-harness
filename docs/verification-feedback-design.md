# v0.2.x Design Draft: Measurement and Feedback (Milestone 12)

Status: **DRAFT — pending human approval. No implementation starts
until this document is approved.** A possible schema migration (005)
falls under `require_human_approval: database_migration` in
`pcl.yaml`, which is why this design is written down before any task
is filed.

Scope: Milestone 12 in `docs/implementation-plan.md` (retrieval eval
suite hardening + verification suggestion feedback loop), plus one
proposed scope amendment (dogfood-to-fixture workflow).

## Why this milestone exists

Two purposes, in priority order:

1. **Investment gating.** The semantic promotion gate says embeddings /
   Tree-sitter / call graphs stay out until the eval suite shows
   missing-critical-context failing to improve under lexical tuning.
   That gate is only meaningful if the eval suite is trustworthy and
   fed by real usage.
2. **Closing the suggestion loop.** v0.1.11 delivers verification
   suggestions into context packs; today they are advice with no
   record of whether anyone acted on them. Without executed/hit/miss
   visibility, PLH cannot evaluate its own suggestions.

An eval whose fixtures do not grow from dogfood examples is not
credible. That is the reasoning behind the proposed scope amendment
below.

## Part 1: Verification suggestion IDs

### Current state

`context-receipt/v0` carries `verification_suggestions` as a plain
list of strings (`receipts.py` → `_receipt_payload`;
`summary.py` passes them through with `_string_list`). Nothing can
reference an individual suggestion.

### Proposal

Evolve the receipt payload (receipt contract is v0/unstable; the
`code-context-summary/v0` isolation layer shields `context-pack/v1`
consumers — this is exactly what the isolation layer was built for):

```json
"verification_suggestions": [
  {
    "id": "E-0001/VS-01",
    "command": "python3 -m pytest tests/test_context.py",
    "reason": "test_hint:path_token_match",
    "status": "suggested"
  }
]
```

- **ID scheme**: `<receipt evidence_id>/VS-<nn>`, deterministic within
  a receipt, ordinal by position. No new DB sequence, no migration
  needed for minting, and the receipt reference is embedded in the ID
  itself.
- `summary.py` and `pcl receipt show` render `command` (display is
  unchanged for humans) and carry `id` in the JSON summary.
- Backward compatibility: `summarize_code_context_receipt` accepts
  both string-list (old receipts on disk) and object-list forms; old
  receipts summarize as objects with `id: null`.

## Part 2: Verification feedback recording

### What we need to record

For a given suggestion: was it executed, skipped, or never seen; if
executed, what happened; and which evidence backs that claim.

```json
"verification_feedback": {
  "suggestion_id": "E-0001/VS-01",
  "status": "executed",        // executed | skipped | not_applicable
  "result": "passed",          // passed | failed | inconclusive (executed only)
  "evidence_id": "E-0009",
  "created_at": "..."
}
```

Epistemic boundary (same discipline as receipts): `executed` +
`result` are claims by the caller recording the feedback, backed by
the referenced evidence artifact. PLH does not verify the command was
actually run; it stores the claim and its evidence pointer. Vocabulary
must not drift into "verified safe".

### Storage options

**Option A — migration 005, new table `verification_feedback`.**
Columns: `id`, `suggestion_id`, `receipt_evidence_id`, `status`,
`result`, `evidence_id`, `created_at`, FKs to `evidence`. Recorded via
a new CLI verb (e.g. `pcl verify feedback --suggestion E-0001/VS-01
--status executed --result passed --evidence E-0009`), never raw SQL.
- Pros: cheap aggregation for eval baselines (hit/miss rates per
  reason, per fixture kind); consistent with how every other loop
  entity is stored; queryable from dashboard-data.
- Cons: requires migration 005 and human approval; one more table.

**Option B — no migration: feedback as a new evidence type
(`verification_feedback`) with a JSON artifact + JSONL event.**
- Pros: zero schema risk; fits "evidence + audit trail" philosophy.
- Cons: aggregation means scanning JSON artifacts; hit/miss metrics
  and baseline history become file-crawling jobs; dashboard-data
  integration is awkward. Experience with `code_index_*` (which got
  tables for exactly this reason) suggests we would migrate later
  anyway.

**Recommendation: Option A** (migration 005), on the grounds that the
whole point of Milestone 12 is aggregate measurement, and measuring
over ad-hoc JSON files is the thing PLH's SQLite-state principle
exists to avoid. Approval decision requested.

## Part 3: Eval baseline history and regression gate

- `pcl eval retrieval --record-baseline`: stores the eval result as
  evidence (JSON artifact under
  `.project-loop/evidence/retrieval-eval/`) plus an event; the
  baseline is identified by fixture file + fixture content hash +
  `pcl` version.
- `pcl eval retrieval --compare-baseline`: compares current metrics to
  the latest recorded baseline for the same fixture hash; reports
  per-metric deltas.
- Gate policy (staged, matching 0080's advisory stance):
  - v0.2.0: comparison output is advisory evidence in CI (like
    today's advisory eval step).
  - Promotion to a blocking gate happens only after baseline history
    exists for the full 5-kind fixture set and thresholds are chosen
    from observed variance, not guessed.
- Metrics per fixture kind (code change, docs-only, config-only,
  rename/move, secret omission): precision, recall,
  missing-critical-context rate, false-positive rate, token cost
  (estimated tokens of included candidate context).

## Part 4 (scope amendment, needs approval): dogfood-to-fixture

Proposed addition to Milestone 12:

- `pcl eval fixture propose --from-receipt <evidence-id>`: generates a
  `retrieval-fixture/v0` candidate from a real receipt — changed
  files, retrieved candidates, and a placeholder `expected` block the
  human fills in (what actually mattered, what was missed).
- Candidates land in a `fixtures/proposed/` staging area; adoption
  into `tests/fixtures/` is a human review step (labels are human
  judgments by definition).
- Rationale: the 2026-07-05 dogfood session produced exactly this kind
  of example by hand (`retrieval_real_history_v0.json`); this command
  makes the pipeline repeatable so fixture growth tracks real usage.

## Explicitly out of scope for v0.2.x

Unchanged from the promotion gate: embeddings, Tree-sitter
requirement, call graphs, semantic retrieval, hosted search,
content-based secret scanning, automatic go/no-go verdicts. Also out:
automatic execution of suggested verification commands (recording is
manual/CLI-driven; auto-execution is a different trust conversation).

## Sequencing

1. 0087 (proposed): suggestion IDs + summary/show compatibility — no
   migration, can start immediately after v0.1.12.
2. 0088 (proposed): migration 005 + `pcl verify feedback` — **blocked
   on approval of this document**.
3. 0089 (proposed): baseline record/compare + CI advisory comparison.
4. 0090 (proposed): dogfood-to-fixture command — blocked on the scope
   amendment decision.

## Decisions requested from the human

1. Storage: approve Option A (migration 005 `verification_feedback`
   table) or direct us to Option B (evidence-only, no migration).
2. Approve the dogfood-to-fixture scope amendment to Milestone 12.
3. Confirm the staged gate policy (advisory first, thresholds from
   observed variance).
4. Confirm the suggestion ID scheme (`<evidence_id>/VS-<nn>`,
   receipt-scoped, deterministic).
