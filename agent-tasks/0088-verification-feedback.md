# Task 0088: Migration 005 + `pcl verification feedback` + `pcl verification stats`

Design source: `docs/verification-feedback-design.md` Parts 2
(approved 2026-07-06) plus the metric refinements recorded in its
approval addendum. Read it before implementing. Where this spec and
the design doc disagree, the design doc wins. Depends on task 0087
(object-form suggestion IDs) being merged.

Migration 005 is approved under
`require_human_approval: database_migration` (approval recorded in the
design doc). Do not add any other table or column.

## Goal

Close the suggestion loop: record whether PLH's verification
suggestions were executed, skipped, or not applicable, as an
append-only trail of caller claims backed by evidence pointers — and
expose observable rates read-only.

## Scope

### 1. Migration 005 (`src/pcl/db/migrations/005_verification_feedback.sql`)

Exactly the approved shape — append-only event table, NO
`UNIQUE(suggestion_id)`:

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

`SCHEMA_VERSION` becomes 5. Confirm the 0076 guards hold: an old
binary against a v5 DB gets the typed DB-ahead rejection, and
`pcl migrate` never downgrades metadata (explicit tests).

### 2. `pcl verification feedback` (under the EXISTING `verification` parser)

```bash
pcl verification feedback --suggestion 'E-0001/VS-01' --status executed \
  --result passed --evidence E-0009 [--note "..."]
```

- Referential honesty: parse the receipt evidence ID from the
  suggestion ID prefix, load that receipt artifact, and verify the
  suggestion ID exists in its payload. Unknown receipt, unreadable
  artifact, or absent suggestion ID → typed errors (distinct codes).
- Validate status/result/evidence combinations at the CLI layer with
  typed errors BEFORE the insert; the SQL CHECK is a backstop, not
  the user-facing error path.
- `--evidence` must reference an existing evidence row.
- Every insert appends a JSONL event (standard audit trail).
- Multiple feedback rows per suggestion are legal by design.
- Help text and docs must frame `executed`/`result` as the CALLER'S
  claim backed by the referenced evidence — PLH does not verify the
  command ran. Never "verified", never "safe".
- Suggestion IDs contain `/`; show quoted usage in help/examples.

### 3. `pcl verification stats --json` (read-only)

Scans all `evidence` rows with `type = 'context_receipt'`, loads each
artifact, extracts suggestions, joins against `verification_feedback`.
Mutates nothing, appends no event.

Approved metric definitions (2026-07-06) — use these exactly:

- **Addressable suggestion**: object-form suggestion with a non-null
  `id`, found in a stored receipt artifact.
- Legacy string-form suggestions (`id: null`) are EXCLUDED from all
  denominators and reported separately as
  `unaddressable_legacy_suggestions_count`.
- Suggestion-level rates (denominator = addressable issued
  suggestions):
  - `feedback_coverage_rate` = suggestions with ≥1 feedback row of
    any status / addressable issued suggestions.
  - `execution_rate` = suggestions with ≥1 `executed` feedback row /
    addressable issued suggestions.
- Feedback-event-level rates (denominator = all `executed` feedback
  events):
  - `executed_pass_rate` = executed events with `result = 'passed'` /
    executed events.
  - `executed_fail_rate` = executed events with `result = 'failed'` /
    executed events.
  - These two need not sum to 1 (`inconclusive` exists); do not add a
    derived inconclusive rate field, it is implied.
- Also report raw counts behind every rate (numerators and
  denominators), and `receipts_scanned` /
  `receipts_unreadable_count`. An unreadable artifact is a warning
  and a count — never a fabricated zero, never a crash.
- Empty denominators → rate `null`, not 0.0.
- Vocabulary: NO hit/miss/usefulness anywhere (fields, help, docs,
  events).

### 4. Documentation

- `docs/data-model.md`: table shape, append-only semantics, derived
  "no feedback recorded" display rule.
- `docs/code-context.md` or a new `docs/verification-feedback.md`:
  feedback CLI, stats contract, epistemic boundary paragraph.
- README: one short example under the verification section.

## Acceptance Criteria

- Migration up from v4 and from a fresh init both yield v5 with the
  exact approved table shape; 0076 never-downgrade and DB-ahead
  rejection tests updated for v5.
- CHECK boundary tests: executed without result → typed CLI error;
  executed without evidence → typed CLI error; skipped with result →
  typed CLI error.
- Unknown suggestion ID / unknown receipt / ID absent from receipt →
  distinct typed errors, nothing inserted, no event appended.
- Same suggestion accepts multiple feedback rows; "latest" is derived
  at read time in stats, never stored.
- Stats fixture test covering: mixed old/new receipts (legacy strings
  counted only in `unaddressable_legacy_suggestions_count`), a
  suggestion with multiple feedback rows (counted once in
  suggestion-level rates, each event counted in event-level rates),
  empty-denominator null rates, and an unreadable artifact warning.
- `pcl validate --strict` checks `verification_feedback` referential
  integrity (receipt_evidence_id and supporting_evidence_id rows
  exist).
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes and `pcl migrate status` reports v5.

## Do Not

- Do not add `UNIQUE(suggestion_id)` or any current-state/status
  column outside the approved shape.
- Do not add a `never_seen` status or store derived states.
- Do not auto-execute suggested commands.
- Do not put feedback state into receipt payloads or summaries.
- Do not add go/no-go fields (`safe_to_continue` etc.).
- Do not create a `pcl verify` alias or namespace.
- Do not use raw SQL against `.project-loop/project.db` outside the
  migration and the service layer.
