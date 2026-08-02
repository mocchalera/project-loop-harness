# 0222: P1-C C4 semantic coverage admission

- **Status:** Implemented locally; independent implementation review pending
- **Milestone:** P1-C C4 trusted semantic coverage admission join
- **Priority:** P1
- **Dependency:** Accepted C3 implementation at
  `f19e72239ca1ad9a8b534d27535388da66330e0d`
- **Schema/dependencies:** SQLite schema 8; migration 0; runtime dependency 0;
  application JSON schemas +2
- **PCL state effect:** 0; no database/filesystem runtime write, Evidence,
  event, outbox, render, lifecycle, or public CLI

## Authorized C4 contract

Implement only the pure in-memory `proof_admission` contract and runtime. A
trusted producer capability binds the exact policy. The evaluator joins live
C2/C3 chains through the Task/candidate/C1/bootstrap/canary coverage group,
validates exact plan/execution bindings and prepared-check identity, resolves
candidate blobs through a sanitized direct `GitRunner`, and derives role,
effect, current-proof, reason, state, reviewability, and promotion facts as
total deterministic functions.

Selectors remain audit labels and are sorted only for audit comparison. Raw
argv remains order-sensitive. C3 verdict, reuse, output commitment, current
proof, anchoring eligibility, and handoff facts are copied without weakening or
reinterpretation. `output_commitment_status` is null exactly for a missing role
and non-null for both not-run and executed roles.

## Exclusions

No persistence, DB write, migration, dependency, Evidence, event, outbox,
render, lifecycle transition, public CLI, hosted/network functionality,
retained-root cleanup, or C5 anchoring/reuse/terminal authorization. Independent
review and any required human gate remain pending. C3's five accepted Low
limitations are carried without modification.

## Verification boundary

Use source-tree execution and disable bytecode and caches:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_proof_admission_contract.py tests/test_proof_admission.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_authority_surface.py tests/test_proof_workspace.py tests/test_proof_execution_contract.py tests/test_proof_execution.py tests/test_proof_admission_contract.py tests/test_proof_admission.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pcl --help
```

The focused matrix covers trusted producer identity, exact preimages, live
C2/C3 identity and tamper gates, distinct proof keys, missing/not-run/executed
nullability, all effect and current-proof branches, aggregate/state precedence,
SHA-1/SHA-256 blob handling and unsupported types, secret/cap rejection,
disclosure exclusions, input permutation, concurrency, and effect zero.
