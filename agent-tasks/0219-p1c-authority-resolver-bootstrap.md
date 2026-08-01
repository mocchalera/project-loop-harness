# 0219: P1-C C1 authority resolver and bootstrap

- **Status:** Implemented locally; external bootstrap verification pending
- **Milestone:** P1-C C1 authority resolution
- **Priority:** P1
- **Size:** M
- **Dependency:** Accepted P1-B C0 at `1f3194bf9b5c39f3ab5fc438a227511dc142bd92`
- **Schema/dependencies:** schema 8; migration 0; runtime dependency 0
- **PCL state effect:** 0; no event, Evidence, render, or lifecycle mutation

## Authorized C1 contract

Implement only the additive `authority-surface-resolution/v1` resolver,
trusted-base derivation, maximum-rank base/candidate catalog and canary union,
optional trusted integration-head config, and external frozen
`bootstrap-authority-profile/v0` validation.

The resolver binds candidate/base/diff/catalog/canary/profile/resolver hashes,
preserves R3/R4 and human gates, assigns the specified R2/R3 authority floors,
and fails unknown executable/runtime paths to at least R2. Candidate input may
add or escalate but cannot delete or weaken trusted requirements.

Task-start `work_started.receipt.repository_revision` has first precedence only
when it is an unambiguous full ancestor. The integration fallback accepts only
an explicitly configured full OID and one merge-base. Caller base is an
assertion. Missing, malformed, ambiguous, non-ancestor, or no-change states do
not permit reuse or low-risk approval.

## Bootstrap limitation

The frozen profile canonical SHA-256 is
`sha256:632fa2a2d50005ea1d6f85c220886cd3e8f644ece720a4d39ceb240847d53eac`.
It requires one exact-candidate full regression and fixed-hash independent
review and forbids self-certification. Local implementation and tests do not
claim either external outcome.

## Exclusions

No C2 Git isolation/external-input materialization, C3 proof run/bundle/event
anchor, C4 parallel join, C5 rollout, proof CLI, reusable suite result, terminal
integration, new Evidence type, default enablement, C0/adaptive-policy Low fix,
schema/migration/dependency change, or external write.

## Verification boundary

Use source-tree execution with bytecode and caches disabled:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_authority_surface.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider <focused regression set>
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider
```

The focused suite must cover underclassification, every maximum-rank input,
base/canary deletion and weakening, unknown paths, base ambiguity/non-ancestor/
no-change, config absence/validation, digest mismatch, and candidate-runtime
self-certification rejection. Mutation checks must demonstrate that minimum/
assignment composition and removal of a risk input are killed by the suite.
