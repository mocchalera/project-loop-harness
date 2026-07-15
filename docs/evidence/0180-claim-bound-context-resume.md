# 0180 Claim-bound context and resume evidence

Date: 2026-07-15

## Scope delivered

- Added deterministic `trace_claim_refs` selection shared by context and resume.
- Emits claims only after `intent-index-binding/v0` is valid, with literal
  `trust: unverified` and exact copied Evidence/path/line references.
- Added complete-item limits of 8 items and 4096 canonical UTF-8 JSON bytes,
  plus `trace_claim_ref_budget` and item-level `packet_budget` omissions.
- Added optional packaged handoff schema/validator fields and JSON-derived
  Markdown rendering.
- Invalid binding emits no claims and records
  `trace_claim_refs:invalid_binding`; ambiguous/context failures preserve typed
  preflight status. No-index packets retain their prior shape.
- Raw trace/source-line text remains absent. Context pack and resume remain
  read-only; no schema migration, dependency, model call, or new entity exists.

## Verification

```text
PYTHONPATH=src pytest -q tests/test_trace_contract_fixtures.py tests/test_context.py tests/test_context_check.py tests/test_resume.py tests/test_handoff_packet_contract.py tests/test_contract_cli.py
110 passed in 17.03s

PYTHONPATH=src pytest -q tests/test_trace_contract_fixtures.py tests/test_context.py tests/test_context_check.py tests/test_resume.py tests/test_handoff_packet_contract.py tests/test_contract_cli.py tests/test_adoption_docs.py tests/test_tasks.py
118 passed in 17.98s

PYTHONPATH=src python -m ruff check .
All checks passed!

PYTHONPATH=src pytest -q
1021 passed, 1 skipped in 213.51s (0:03:33)

git diff --check
exit 0
```

## Boundaries retained

- Claim wording never enters `verified`, Decision state, or next-action
  authority.
- The packaged minimal `handoff-packet/v1` fixture remains valid without any
  trace-claim fields.
- Existing unrelated dirty work remains outside this evidence claim.
