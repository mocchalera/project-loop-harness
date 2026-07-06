# Task 0090: Eval Baseline Record / Compare (v0.2.1)

Design source: `docs/verification-feedback-design.md` Part 3 plus the
Approval addendum. Where this spec and the design doc disagree, the
design doc wins. Depends on task 0089 (unlabeled-fixture guard) being
merged. No migration, no new runtime dependency.

## Goal

Make retrieval eval results durable, comparable evidence with full
provenance, so the semantic promotion gate can eventually be decided
by evidence instead of enthusiasm. Metric thresholds stay ADVISORY;
only broken measurement infrastructure blocks.

## Scope

### 1. Metrics completion (additive to `retrieval-eval/v0` output)

- Add `false_positive_rate` = (retrieved_total − true_positive_total)
  / retrieved_total (aggregate and per task; `null` on empty
  denominator — same rule as everywhere else).
- Add `token_cost_estimate` = deterministic `charclass/v1` estimate
  over the retrieved candidate files' indexed content (per task and
  aggregate). Reuse the existing estimator; document the basis
  (indexed bytes, not live file reads) in the output field name or
  docs — it is an estimate label, never a billing claim. Files
  missing from the index contribute 0 and are listed in a
  `token_cost_unestimated_paths` array rather than silently skipped.
- Existing precision / recall / missing_critical_context stay
  unchanged.

### 2. Fixture kind coverage (5 kinds)

The approved kinds: code change, docs-only, config-only, rename/move,
secret omission. Code change, rename/move, and secret omission
already exist (`retrieval_v0.json`, `retrieval_adversarial_v0.json`).
Add small labeled fixture tasks for **docs-only** and **config-only**
changes in the same synthetic style. Keep the existing floor-test
discipline: assert metric floors per fixture in tests so regressions
fail loudly.

### 3. `pcl eval retrieval --record-baseline`

- Runs the eval, then stores the full evaluation payload as a normal
  evidence artifact under `.project-loop/evidence/retrieval-eval/`
  (evidence row + JSONL event, following the receipt-recording
  pattern).
- Baseline artifact carries a `baseline_provenance` block with ALL
  SIX approved fields, each REQUIRED:
  1. `fixture_path` + `fixture_content_hash` (sha256 of fixture
     bytes),
  2. `git_head` of the target repo,
  3. `index_run_id` + `index_detail_hash` (hash of the index detail
     artifact),
  4. `code_context_config_hash` (hash of the effective `code_index`
     config subtree from `pcl.yaml`, canonicalized),
  5. `pcl_version` (the real `pcl.__version__`),
  6. `eval_contract_version` (`retrieval-eval/v0`).
- Missing provenance input (e.g., no index run exists, not a git
  repo) → typed error, nothing recorded. Broken provenance is not a
  baseline.

### 4. `pcl eval retrieval --compare-baseline`

- Finds the LATEST recorded baseline whose `fixture_content_hash`
  matches the current fixture; reports per-metric deltas
  (precision, recall, missing-critical-context count,
  false_positive_rate, token_cost_estimate) plus both provenance
  blocks side by side.
- No baseline with a matching fixture hash → typed
  "not comparable" error naming the nearest baseline and why it does
  not match (hash mismatch is stated explicitly, never silently
  compared).
- Comparison output is a report, not a verdict: deltas and facts
  only. No pass/fail field, no threshold evaluation.

### 5. CI advisory comparison

- Extend `scripts/run_advisory_retrieval_eval.py` (or add a sibling
  script wired the same way) so CI runs the eval and, when a
  committed baseline reference exists, prints the comparison as an
  advisory artifact.
- Metric regressions NEVER fail CI.
- Eval INFRASTRUCTURE failures DO fail CI: eval command error,
  fixture contract violation, unreadable fixture, provenance
  computation failure. Broken measurement is not advisory.

### 6. Documentation

- `docs/code-context.md` eval section: baseline lifecycle, the six
  provenance fields, the advisory-vs-blocking boundary, and the
  semantic promotion gate linkage (evidence decides promotion).

## Acceptance Criteria

- Recording twice on an unchanged repo+fixture yields identical
  metrics and identical provenance except evidence id/created_at.
- Compare on matching hash reports per-metric deltas; compare after
  editing the fixture → typed not-comparable error that names the
  hash mismatch.
- Missing index run → typed error from `--record-baseline`, no
  evidence row, no event.
- `false_positive_rate` and `token_cost_estimate` appear per task
  and aggregate, `null` on empty denominators;
  `token_cost_unestimated_paths` lists unindexed files.
- Docs-only and config-only fixture tasks exist with floor tests.
- CI script: a deliberately corrupted fixture fails the script
  (blocking path test); a metric delta does not (advisory path
  test).
- `pcl validate --strict` untouched by baselines beyond standard
  evidence integrity.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not implement metric thresholds, pass/fail verdicts, or release
  gates on metric values.
- Do not compare across different fixture hashes "helpfully".
- Do not read generated dashboard HTML, mutate state from the eval
  path beyond the evidence row + event, or add raw SQL.
- Do not use hit/miss/usefulness vocabulary; token cost is an
  estimate, not a price.
- Do not touch embeddings / Tree-sitter / call graphs — the semantic
  promotion gate is unchanged.
