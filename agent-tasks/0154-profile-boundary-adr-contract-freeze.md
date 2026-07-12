# 0154: Profile boundary ADR and proposal contract freeze

- **Status:** Done; ADR accepted by human owner on 2026-07-12
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P0
- **Size:** M
- **Dependencies:** 0153b; human Accept/Modify/Reject of the Profile boundary
- **DB schema:** no change

## Goal

Freeze the model-independent PLH/external-runner boundary and the seven
artifact shapes before adding runtime Profile behavior.

## Scope

- Add ADR-005 and the Council proposal under `docs/proposals/council-profile/`.
- Add seven proposal schemas plus canonical positive and targeted negative
  fixtures outside the runtime package.
- Resolve the unshipped `decision-proposal/v0` shape conflict in the integrated
  roadmap and update its example/references atomically.
- Record canonical JSON/digest, status, path, size, and cross-reference rules.
- Define request-basis digest and embedded `approval-provenance/v1` binding for
  paid/network authorization without a circular request digest.
- Freeze exact request-basis exclusions for generated time and context receipt
  age fields while retaining receipt timestamps, source refs, and hashes.
- Define project fingerprint inputs and confirm only the digest is emitted.
- Define how `claim-set/v0` classes map to normal Evidence, Verification,
  Decision, Work Brief, residual risk, and completion-packet boundaries.
- Record the terminology contract: route profile, runner Profile ID, and role
  profile use distinct JSON fields, help text, and error language.
- Record that MVP is v0.5.0, built-in-only, schema 8, and strict-human-gated.

## Invariants

- No runtime Profile command, provider code, network, credential, external
  execution, DB migration, or state mutation.
- No two incompatible shapes remain documented under one contract version.
- Model judgment is never deterministic proof.

## Acceptance

1. ADR has an explicit human outcome.
2. Seven schemas are valid JSON, declare Draft 2020-12, and have canonical
   examples plus a validation transcript. Runtime conformance is implemented
   by 0155 standard-library validators; no dependency is added.
3. Negative fixtures cover unknown fields, unsupported versions, bad status,
   bad references, and invalid digest/path declarations.
4. The old decision-proposal draft has a visible supersession note.
5. Authorized-policy fixtures prove any semantic request change invalidates the
   approval binding.
6. Candidate and authorized requests built at different wall-clock times have
   the same basis digest when semantic state is unchanged.
7. Claim-to-proof and terminology mappings have no implicit promotion path.
8. `ruff check .` and full `pytest` pass without dependency changes.
