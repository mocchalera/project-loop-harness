# 0178 Trace contract and fixture freeze evidence

Date: 2026-07-15

## Scope delivered

- Characterized current `master_trace_context` and `pcl resume` behavior as
  reference-only: raw trace/index text is not inlined, `trace_claim_refs` is
  absent, and model claims do not enter `verified`.
- Frozen a valid trace/index binding and isolated invalid fixtures for SHA-256,
  Evidence ID, manifest path, copied stored path, unsupported contract,
  duplicate item ID, empty refs, reversed range, and out-of-bounds range.
- Frozen the future optional `trace_claim_refs` field name, ordering, trust
  label, bounded source-ref shape, and omission reasons without changing the
  packaged handoff schema or runtime.
- Frozen the 0181 controlled evaluation cohort, result fields, and promotion
  thresholds for success, assistance, safe stop, byte size, and trust-boundary
  violations.
- Documented the distinction between artifact identity, source-address
  validity, and semantic correctness.

## Verification

Targeted contracts and affected behavior:

```text
PYTHONPATH=src pytest -q tests/test_trace_contract_fixtures.py tests/test_context.py tests/test_resume.py
82 passed in 15.19s
```

Static and diff checks:

```text
PYTHONPATH=src python -m ruff check tests/test_trace_contract_fixtures.py tests/test_context.py tests/test_resume.py
All checks passed!

git diff --check
exit 0
```

Full regression suite:

```text
PYTHONPATH=src pytest -q
1015 passed, 1 skipped in 192.32s (0:03:12)
```

## Boundaries retained

- No runtime behavior, database schema, dependency, LLM call, or external
  service was added.
- Existing `handoff-packet/v1` remains unchanged and rejects unknown fields;
  implementation of the additive field remains assigned to 0180.
- The repository already contained unrelated dirty work. This evidence covers
  only the files named by 0178 and does not claim a clean worktree.
