# Durable Proof Admission Anchor v1

P1-C C5 admits one live C4 `reviewable` proof-admission basis into a durable,
immutable local artifact. It adds only anchor-scoped authorization. It does not
authorize proof reuse, terminal readiness, a lifecycle transition, mandatory
Evidence policy, promotion, publication, deployment, network access, or any
external right.

The embedded C4 document remains unchanged and must retain:

```text
anchoring_authorized=false
reuse_authorized=false
terminal_authority=false
mandatory_evidence=false
```

C5 records its separate decision as `anchor_authorization_granted=true`.

## Contracts and digest boundary

The application contracts are Draft 2020-12 JSON Schemas:

- `proof-admission-anchor-basis/v1`
- `proof-admission-authorization/v1`
- `proof-admission-anchor/v1`
- `proof-admission-anchor-result/v1`

All documents use UTF-8 canonical JSON with sorted keys, compact separators,
no trailing newline in digest preimages, and domain-separated SHA-256 digests.
Stored JSON members add exactly one newline after the canonical bytes. The
manifest is non-self-referential: its ordered members are `basis`,
`independent_review`, then optional `human_gate`. Evidence, event, and outbox
identifiers are assigned only after the artifact precommit and are absent from
the manifest. Event payloads expose only request, basis, anchor, manifest-file,
generation, and Evidence identities; they never expose actor, source, reason,
or review-report bytes.

The contract caps are 34,603,008 basis bytes, 65,536 authorization bytes,
1,048,576 manifest bytes, 131,072 event-payload bytes, and 37,748,736 bytes for
the final directory. Canonical validators reject unsupported fields, invalid
nullability or ordering, secret-shaped content, and changed relationship or
digest bindings.

Authorization documents are created only through a private live issuer
capability registry. The runtime takes detached deep copies and recursively
freezes the trusted result. Independent-review and required human-gate actors
must both have `candidate_controlled=false`; each must be independent of the C4
policy producer. Existing approval-provenance actor, recorder, source, and
redaction rules remain authoritative.

## Locked admission and atomic success

`anchor_proof_admission` is an internal library API, not a public CLI. It
accepts live C2/C3/C4 objects; a caller cannot submit a serialized C4 result.
Under the project lock and `BEGIN IMMEDIATE`, it recomputes the live C4 basis,
current-proof snapshot, authority merge, exact canary resolution, candidate,
review/human authorization, and every receipt, subject, request, epoch, anchor,
health, and digest. The outbox must be fully delivered before admission.

Fresh success publishes one immutable artifact directory and inserts exactly
one Evidence row, one Task link, one `proof_admission_anchored` Task event, and
one outbox row in the same mutation transaction. SQLite commit is the business
linearization point. Recoverable JSONL projection runs after commit. Exact
replay has zero effects. A precommit conflict or guard failure has zero database
effects and removes only the exact retained-descriptor artifact it created;
ambiguous artifacts are never recursively removed. Projection failure exits 6
and is recovered by projection flush without replaying business DML.

The shared strict Evidence directory primitive enforces canonical parent/path
identity, no-follow lookup, regular single-link members, case-fold uniqueness,
exclusive file creation and directory publication, retained descriptor/inode
receipts, file and directory fsync, and exact-receipt cleanup. Symlinks,
hardlinks, path aliases, replacement races, and unexpected directory members
fail closed. Audit reports orphan staging and final directories by request hex
plus anchor hash; an Evidence ID is never used as an orphan identity.

## Recovery and exhaustion

Every committed chain is enumerated for the target Task and basis before
caller-subject routing. Rows are grouped by `base_request_sha256`, and each
unique contiguous head is validated. Classification order is fixed:

1. valid recovery-exhaustion tombstone;
2. no anchor rows;
3. any valid unhealthy generation-3 witness;
4. malformed, forked, or gapped authority;
5. multiple valid chains;
6. one valid chain.

Any existing chain blocks a different-base generation 0, even if its head is
unhealthy. Health recovery is generation-specific and bounded by
`MAX_RECOVERY_GENERATIONS=3`. The predecessor is reread strictly and the final
guard rederives its receipt; callers cannot choose generation, predecessor, or
IDs. If generation 3 is unhealthy, the first recovery-exhaustion decision
appends one subject-independent `proof_admission_anchor_recovery_exhausted`
Task event and one outbox row, with no Evidence, link, or filesystem write.
Its identity is keyed by project instance, target Task, and basis. Exact replay
has zero effects; projection failure exits 6.

One accepted Low risk remains: a chain whose head is unhealthy at generation
0–2 cannot advance without an actor registered under the chain's `actor_id`.
The runtime fails closed with `proof_anchor_existing_chain_recovery_required`,
including the required next generation. A different candidate derives a new
basis; C5 never opens a parallel chain for another reviewer.

## Audit and later phases

`pcl audit` and strict validation reread committed event authority and then
assess the immutable artifact. Corrupt artifact facts cannot replace committed
request, generation, basis, anchor, or manifest identities. Unhealthy committed
anchors and orphan paths are reported, but never adopted or repaired by C5.

SQLite remains schema version 8. C5 applies no migration and adds no runtime
dependency. C6 or later work must separately design any reuse, terminal,
mandatory-Evidence, lifecycle, or publication consumer.
