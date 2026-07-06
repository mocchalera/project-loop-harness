# Task 0080: Retrieval Eval — Schema Docs, Adversarial Fixtures, Advisory CI

## Goal

Make `pcl eval retrieval` trustworthy enough to inform future design
decisions (semantic retrieval, Tree-sitter, call graphs) WITHOUT
turning it into a release gate yet. Gate-tightening before dogfood data
exists would make the eval harness itself a vanity project.

Scope is deliberately reduced (agreed): fixture schema documentation,
a real-history / adversarial split, three adversarial fixtures, and an
advisory (non-failing) CI run. Threshold-based release blocking comes
later, only after dogfood data accumulates.

## Design constraints (agreed, do not relitigate)

- Eval results are ADVISORY in v0.1.11. CI must not fail on metric
  values; it may fail on broken fixtures or crashed eval runs.
- The blocker-promotion condition is documented, not implemented:
  thresholds become release blockers only after real-project dogfood
  data exists.
- The policy that semantic / Tree-sitter / call-graph additions require
  demonstrated eval improvement is documented; concrete thresholds are
  NOT set yet.
- No new runtime dependencies, no schema migration. Additive evolution
  of `retrieval-fixture/v0` only.

## Scope

### 1. Fixture schema documentation

- In `docs/code-context.md` (Retrieval Evaluation section), fully
  document `retrieval-fixture/v0`: required/optional fields per task
  (`diff` / `query`, expected paths, task metadata), file layout, and
  the evolution rules (additive only; unknown fields ignored; version
  bump criteria).
- Document the two fixture families and their intent:
  - `real-history`: derived from actual repo changes (the existing
    `tests/fixtures/retrieval_real_history_v0.json` pattern);
    measures ordinary retrieval quality.
  - `adversarial`: synthetic cases designed to catch safety/trust
    regressions rather than average quality.

### 2. Adversarial fixtures (three, with tests)

Create adversarial fixture(s) (either one file with tagged tasks or
separate files under `tests/fixtures/`) covering exactly these three
cases, each exercised by a pytest test that runs the real eval path
against a temp project:

- **secret-like omission**: a project containing sensitive-pattern
  files (`.env`-like, key-like). Expectation: those paths never appear
  in retrieved results, and the index records
  `sensitive_omitted_count > 0`. The test asserts the eval run itself
  plus the omission invariant.
- **stale index**: index built, then a fixture-relevant file modified
  without rebuilding. Expectation: eval output (or the search results
  it consumes) carries the staleness signal; the test asserts the
  staleness warning is present and the eval does not silently report
  fresh.
- **renamed file**: a file renamed after indexing (or a diff containing
  a rename). Expectation captured honestly: if current lexical
  retrieval misses the rename, the fixture records that as the KNOWN
  baseline (expected-miss annotation), so a future improvement shows up
  as a measurable delta rather than an invisible fix.

### 3. Eval output completeness

- `pcl eval retrieval --json` output gains (additively) whatever small
  fields are needed so the adversarial assertions are machine-checkable
  from the eval result alone where practical (e.g. per-task retrieved
  paths are already exposed; add per-task `staleness_warnings` or an
  `advisory` note only if required by the tests above). Do NOT redesign
  the metrics; recall/precision stay as-is.

### 4. Advisory CI step

- Add a step to `.github/workflows/ci.yml` (after pytest) that runs the
  eval against the checked-in fixtures and prints the JSON summary.
- The step must be advisory for metric values: use
  `continue-on-error: true` OR construct the invocation so only
  crashes/broken fixtures fail (typed fixture errors already exist).
  Prefer a small `scripts/` or make-style entry if it keeps ci.yml
  readable; no new dependencies.
- Document in `docs/code-context.md`: what the CI step does, that it is
  advisory, and the promotion condition (dogfood data → thresholds →
  blocker).

## Acceptance Criteria

- `retrieval-fixture/v0` schema and evolution rules are documented in
  docs; a fixture with unknown extra fields still evaluates (test).
- Broken fixture (missing tasks, invalid JSON) produces the existing
  typed error (regression test if not already covered).
- Three adversarial cases exist as fixtures + passing pytest tests:
  secret-like paths never retrieved; stale index surfaces a staleness
  signal in the eval flow; renamed-file baseline recorded with an
  expected-miss annotation.
- CI workflow contains the advisory eval step; metric values cannot
  fail the build, fixture breakage can.
- Docs state the advisory status, the blocker-promotion condition, and
  the eval-evidence requirement for semantic/Tree-sitter/call-graph
  proposals.
- `ruff check .` passes; full `python3 -m pytest` passes (359 currently
  green, plus new tests); `pcl init` smoke against a temp dir passes.
- No new runtime dependency, no schema migration, no
  `retrieval-fixture/v0` version bump (additive only).

## Do Not

- Do not make eval metrics fail CI or block releases.
- Do not set concrete recall/precision thresholds yet.
- Do not add new metrics beyond what the three adversarial assertions
  need; no metric framework redesign.
- Do not add embeddings, Tree-sitter, call graphs, or semantic
  retrieval.
- Do not add content-based secret detection; the secret fixture tests
  the existing path/pattern omission.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
