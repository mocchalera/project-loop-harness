# Proof coverage admission v1

P1-C C4 is an internal, pure in-memory join over live C2 workspaces and their
exact C3 execution bundles. It answers whether a trusted semantic coverage
policy is factually reviewable. It does not persist, anchor, authorize, or
change Project Loop state.

## Contracts and trusted producer

C4 adds exactly two strict Draft 2020-12 application schemas:

1. `proof-coverage-policy/v1`
2. `proof-coverage-admission/v1`

The policy binds a Task, full candidate commit/tree and object format, current
C1/bootstrap/canary-union authority, exactly one full-regression requirement,
and exactly one requirement for every effective authority canary. Each
requirement fixes the raw C2 check, order-sensitive argv, declared environment,
tool/public/spawn/external-input bindings, sorted audit labels, candidate blob
bindings, and domain-separated hashes.

Raw mappings cannot enter the evaluator. The application composition root
issues an in-process producer capability associated with the exact producer
kind and ID. Binding checks the strict policy, every nested digest, the caller's
expected full policy hash, the live capability object identity and registry
tuple, canonical size bounds, and fixed secret-shaped identifier scan. The
capability is neither serialized nor hashed and is not cryptographic authority
against a malicious trusted caller.

## Live C2/C3 join

Every participant carries one live `PreparedProofWorkspace`, its exact C2
spec/C1/bootstrap/verification inputs, and its C3 `ProofExecutionBundle`.
C4 rejects serialized or copied prepared-check objects: C3's frozen packet must
contain the same `PreparedCheck` instances in profile order. All C2/C3 public
documents and self-digests are revalidated before use.

Distinct C2 proof keys are expected across parallel roles. Participants join
through one common coverage group containing the Task, candidate object
format/commit/tree, C1 resolution digest, bootstrap digest, effective canary
union digest, and isolation contract. Duplicate bundles, proof keys, or role
matches are factual invalid outcomes; a live object/digest invariant failure is
a hard error with no admission document.

C4 rechecks source root/common/object-store identities and resolves the exact
commit, tree, object format, and ref reachability through the retained sealed
`GitRunner`. Candidate paths use only a literal `ls-tree -z --full-tree`
lookup. Regular `100644` and `100755` blobs are accepted with full SHA-1 or
SHA-256 OIDs. Missing paths, OID mismatch, symlink/gitlink/tree/unknown types,
and indeterminate Git observations stay distinct. Raw paths, OIDs, Git argv,
stdout, and stderr are not disclosed.

After candidate-tree reads, C4 repeats the source checkpoint, rederives current
C1, and captures one join-final current proof. The final match function compares
all admitted participants, including role-less and unselected duplicates:

```text
indeterminate if final or any participant is indeterminate
mismatched    else if any participant changed or tuple differs
matched       otherwise
```

An executed role's freshness uses `indeterminate > stale > current`; missing
and not-run roles are exactly `not_observed`. State reasons are generated
independently from all source predicates, so annotation tamper cannot hide a
changed, unhealthy, or indeterminate proof. Participant ordering cannot change
the document or its hash.

## Attempt nullability and effects

The role-observation nullability is explicit:

| Field | missing | not_run | executed |
|---|---:|---:|---:|
| matching checks | empty | non-empty | non-empty |
| selected participant/check | null | non-null | non-null |
| attempt/result/receipt/C3 verdict | null | null | non-null |
| aggregate facts | null | non-null | non-null |
| `output_commitment_status` | null | non-null | non-null |
| candidate blob resolution digest | null | non-null | non-null |

The explicit `output_commitment_status` row closes independent design-review
Low L-H; it must not be inferred from a compressed “aggregate fields” label.

Recognized canary expectations are
`canonical-product-inputs-unchanged` and `pcl-state-effect0`. The total effect
precedence is unsupported, canonical mismatch, unproved PCL HWM equality, then
`not_disproved` or `satisfied`. The PCL claim is limited to the C3 bundle's
read-only current-proof HWM observations and does not prove absence of raw
SQLite no-event writes.

## State and authorization

Admission state precedence is:

```text
invalid > indeterminate > stale > blocked > incomplete > reviewable
```

All true reason edges are retained even when a higher state wins.
`review_readiness=ready` only for `reviewable`. Promotion suitability is a
separate factual projection and is withheld for any participant with
fresh-only reuse, uncommitted output, anchoring ineligibility, or withheld C3
handoff.

Authorization never follows from those facts:

```text
independent_review = pending
human_gate         = pending | not_required
anchoring_authorized = false
reuse_authorized     = false
terminal_authority   = false
mandatory_evidence   = false
```

## Effects and C5 boundary

The two JSON schema files are application artifacts. The admission's runtime
effect receipt remains all zero: schema/migration/database/filesystem/Evidence/
event/outbox/render/lifecycle. SQLite remains schema 8; migrations,
dependencies, public CLI, network, hosted functionality, and PCL mutations are
zero.

C5 or later owns durable policy/review/human authorization, epochs and replay
prevention, artifacts, SQLite migration, transactional HWM/current-proof/tree
rechecks, Evidence/event/outbox projection, public service/CLI, and terminal or
lifecycle integration. C4 reviewability is not anchor, reuse, or terminal
authorization.
