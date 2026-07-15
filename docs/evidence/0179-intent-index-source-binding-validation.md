# 0179 Intent-index source-binding validation evidence

Date: 2026-07-15

## Scope delivered

- Added a standard-library `intent-index/v0` structural validator to the
  existing `pcl contract validate` family.
- Added source binding against linked copied Evidence: Evidence ID,
  manifest/member/copied path, recorded and actual trace/index SHA-256, unique
  item IDs, non-empty refs, and one-based inclusive line bounds.
- Extended task `pcl context check` with `intent-index-binding/v0`, exact trace
  and index identities, typed diagnostics, and `invalid_binding` safe stop.
- Kept structural-only, source-binding, and semantic validation explicitly
  separate. Model claims are not verified or selected.
- Preserved ambiguity/no-index behavior and read-only operation. No schema,
  dependency, mutation command, provider, or LLM call was added.

## Verification

```text
PYTHONPATH=src python -m ruff check src/pcl/context.py src/pcl/contracts/intent_index.py src/pcl/contracts/__init__.py src/pcl/cli.py tests/test_context.py tests/test_context_check.py tests/test_trace_contract_fixtures.py tests/test_contract_cli.py
All checks passed!

PYTHONPATH=src pytest -q tests/test_trace_contract_fixtures.py tests/test_context_check.py tests/test_context.py tests/test_contract_cli.py
88 passed in 13.31s

PYTHONPATH=src pytest -q tests/test_trace_contract_fixtures.py tests/test_context_check.py tests/test_context.py tests/test_contract_cli.py tests/test_adoption_docs.py tests/test_tasks.py
96 passed in 13.02s

PYTHONPATH=src pytest -q
1018 passed, 1 skipped in 199.43s (0:03:19)

git diff --check
exit 0
```

The invalid-binding E2E mutates a copied index after Evidence capture and
confirms `recorded_intent_index_hash_mismatch` while database rows, events, and
artifact counts remain unchanged.

## Boundaries retained

- `pcl contract validate --type intent-index/v0` is structural only and emits
  `evidence_binding_checked: false`.
- `pcl context check` reports `semantic_validation: false` even for a valid
  binding.
- Existing unrelated dirty work remains outside this evidence claim.
