# Authority surface resolution v1

P1-C C1 adds a read-only authority resolver. It does not add a `pcl proof`
command, run checks, write proof artifacts, append events, create Evidence, or
change terminal readiness. C2–C5 remain outside this slice.

## Contracts

`authority-surface-resolution/v1` binds:

- the exact Task target, candidate commit/tree OIDs, trusted-base result, and
  canonical base-to-candidate Git diff entries plus SHA-256;
- packaged-minimum, trusted-base, candidate, effective-union, and catalog-diff
  SHA-256 values;
- packaged-minimum, base, candidate, effective-union, and canary-diff SHA-256
  values;
- the trusted resolver version/source/SHA-256 and external bootstrap profile
  ID/SHA-256;
- every input floor, the effective risk/depth, human-gate requirement, reuse
  eligibility, and deterministic reason codes;
- literal `terminal_authority: false` and `mandatory_evidence: false`.

The associated catalog and canary documents are
`authority-impact-catalog/v1` and `authority-canary-contract/v1`. All documents
are canonical-JSON hashable. The resolver rejects a diff digest that does not
match its mode/blob/status/path entries.

Risk is the maximum rank across the existing route risk, trusted floor,
packaged minimum, trusted-base catalog, candidate catalog, reviewer escalation,
and fail-closed base state. Verification depth is also maximum-rank composed;
`human` cannot become `independent`. R3/R4 set a human gate, and R4 requires
human verification.

Catalog union is by rule ID. Patterns are unioned and risk is the maximum.
Candidate omission leaves a base rule in place; candidate weakening cannot
lower it. Canary omission also leaves the trusted item in place. An overlapping
candidate canary must preserve its command, required outcome, and platform
conditions, and may only add claims/selectors/blob OIDs/effect expectations.

## Minimum floors

The external bootstrap profile freezes these minimums:

- R2: authority resolver/catalog/profile, adaptive/proof policy, canary,
  proof-key/anchor validation, terminal transitions, current Evidence,
  replay/recovery, mutation tail, project locks, and receipt/acceptance
  authority surfaces;
- R3: schema/migration, dependencies, permissions, and durability mechanisms;
- R2: any otherwise unknown executable/runtime path, and any path not
  explicitly classified as non-executable documentation/presentation.

Overlaps always take the maximum, so an R0 documentation match cannot weaken
an R2/R3 authority match.

## Trusted base

`derive_trusted_base_for_task` reads all matching append-only `work_started`
events without a history limit. Exactly one well-formed
`receipt.repository_revision` must resolve to a full commit ancestor. If no
task-start event exists, the resolver may use the single merge-base between the
candidate and an explicitly trusted integration-head full OID:

```yaml
authority:
  trusted_integration_head_oid: "0123456789abcdef0123456789abcdef01234567"
```

This optional flat `pcl.yaml` field is parsed with the standard library. An
absent section preserves existing configuration behavior and yields
`base_unknown` when no valid task-start anchor exists. A malformed value,
ambiguous task-start provenance, non-ancestor start, invalid/ambiguous
merge-base, or unverifiable source fails closed. A caller base is only an
assertion against the derived value. `base == candidate` is
`no_candidate_change`, never low-risk approval. Both `base_unknown` and
`no_candidate_change` enforce R2 minimum and forbid reuse.

## External bootstrap boundary

The repository fixture
`tests/fixtures/authority_surface/bootstrap-authority-profile-v0.json` is a
test copy of the frozen `bootstrap-authority-profile/v0` document. Its canonical
digest is:

```text
sha256:632fa2a2d50005ea1d6f85c220886cd3e8f644ece720a4d39ceb240847d53eac
```

That document requires an exact-candidate full regression and fixed-hash
independent review, and fixes `self_certification_allowed` to `false`. A C1
candidate and its in-repository fixture cannot approve themselves: review must
receive the frozen external bytes/digest independently and assess the exact
candidate commit. Resolver source provenance is explicitly one of trusted-base,
pinned-installed, or external-bootstrap; candidate runtime is rejected.

This implementation task produces neither bootstrap approval nor reusable
proof. Those remain external review outcomes. The profile is not a new
mandatory Evidence type and has no Feature, Task, or Goal terminal authority.

## Compatibility

- SQLite schema: 8 (unchanged)
- migrations: 0
- runtime dependencies: 0
- adaptive policy: unchanged and not credited with these floors
- `verification-input-manifest/v1`: unchanged
- `check-result-reuse/v1`: unchanged
- default enablement: none
