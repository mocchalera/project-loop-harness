# 0223: P1-C C5 durable proof admission anchor

- **Status:** Implemented locally; independent implementation review pending
- **Milestone:** P1-C C5 durable proof admission and anchor authorization
- **Priority:** P1
- **Dependency:** Accepted C4 implementation boundary at
  `9647b615210c40650790e3b6618ad6dcfaf1ea9e`
- **Design authority:** C5 design task `e019d9eb` seq1–seq4 and independent
  design review `77025668` final GO (High 0, Medium 0, Low 1)
- **Schema/dependencies:** SQLite schema 8; migration 0; runtime dependency 0;
  application JSON schemas +4
- **Public surface:** Internal library API only; no public CLI

## Authorized C5 contract

Implement only the durable `proof_admission_anchor` artifact, private live
anchor-authorization boundary, atomic Evidence/link/event/outbox mutation,
strict local publication, bounded health recovery, subject-independent
recovery-exhaustion tombstone, and audit/validation support described in
`docs/proof-anchor-v1.md`.

The runtime consumes live C2/C3/C4 objects and recomputes current proof,
authority, candidate, canaries, authorizations, receipts, and digests under the
project lock and `BEGIN IMMEDIATE`. Fresh success commits exactly one immutable
artifact, Evidence row, Task link, Task event, and outbox row. Exact replay and
all precommit failures have zero effects. JSONL projection recovery must not
replay business DML.

The C4 document is immutable and retains `anchoring_authorized=false`,
`reuse_authorized=false`, `terminal_authority=false`, and
`mandatory_evidence=false`. C5 records only the distinct
`anchor_authorization_granted=true` decision.

## Exclusions

No reuse authorization, terminal-readiness input, lifecycle transition,
mandatory Evidence policy, promotion, publication, deployment, network or
external write, hosted service, telemetry, public CLI, schema migration, or
runtime dependency. C5 does not implement C6 and does not auto-terminalize a
Feature, Task, or Goal.

## Verification boundary

Use source-tree execution and isolated retained base-temp roots:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider --basetemp <unique-retained-root> tests/test_proof_anchor_contract.py tests/test_strict_evidence.py tests/test_proof_anchor.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider --basetemp <unique-retained-root> tests/test_authority_surface.py tests/test_proof_workspace.py tests/test_proof_execution_contract.py tests/test_proof_execution.py tests/test_proof_admission_contract.py tests/test_proof_admission.py tests/test_proof_anchor_contract.py tests/test_strict_evidence.py tests/test_proof_anchor.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m ruff check --no-cache .
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider --basetemp <unique-retained-root>
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pcl validate --strict --json
```

The focused matrix covers independent golden digests and schema mutation
kills, authorization collisions and deep-copy/freeze behavior, live authority
and canary drift, strict filesystem attacks, rollback and exact replay, 16-way
same and mixed requests, reviewer races on unhealthy generations 1 and 3,
basis-wide parallel/fork/gap authority, every publication/transaction crash
boundary, external final-guard tampering, projection-only recovery, exhaustion,
IDs, effects, audit, and strict validation.

The retained Low risk is that an unhealthy generation 0–2 chain can advance
only through an actor still registered under that chain's `actor_id`. The
fail-closed disposition names the required recovery generation; a different
candidate produces a new basis.
