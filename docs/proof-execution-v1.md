# Proof execution v1

P1-C C3 is an internal, effect-zero proof executor. It runs the exact frozen
`PreparedCheck` objects produced by C2 and returns deterministic, hash-bound
documents in memory. It does not add a public command, store an anchor, or
change Project Loop state.

## Boundary

C3 adds seven strict Draft 2020-12 application contracts:

1. `proof-execution-packet/v1`
2. `proof-authority-checkpoint/v1`
3. `proof-stream-log/v1`
4. `proof-check-execution-receipt/v1`
5. `proof-check-execution-result/v1`
6. `proof-execution-result/v1`
7. `proof-execution-bundle-receipt/v1`

Every selected field is required, extra fields are rejected, arrays and
identifiers are bounded, digests are lowercase `sha256:<64hex>`, and canonical
JSON uses the existing `proof_document_sha256` rules. Public documents omit
PIDs, PGIDs, paths, temp roots, time or duration, random identifiers, raw
exceptions, environment values, tool paths, secret-derived digests, and raw
uncommitted-output facts. `reuse_authorized` is always `false`.

The aggregate `current_proof.proof_sha256` is strictly `sha256 | null`. Null is
permitted only for an `indeterminate` observation. Positive handoff is a
suitability statement, not an anchor:

```text
anchoring_eligible=true  <=> positive_proof_handoff=candidate
anchoring_eligible=false <=> positive_proof_handoff=withheld
```

Eligibility additionally requires a passed complete prefix, no not-run suffix,
a final authority checkpoint, conclusive C2 reseals with only read-only or
declared-output effects, committed output for every stream, and current proof
that is `healthy` or `not_applicable`.

## Frozen spawn and authority

C2's `PreparedCheck` is the sole spawn vector. C3 never resolves PATH, bridges
an unresolved executable, rebuilds argv/cwd/environment, or reads the original
symlink chain again. Symlink provenance is preparation-time information only.
At execution C3 reads the resolved absolute target with no-follow descriptor
checks and revalidates its stat identity, bytes, portable mode, and shebang
interpreter digest.

Canonical source authority is the C2-retained source root, Git common
directory, object store, and object format. At every full checkpoint C3:

- verifies those directory identities without following symlinks;
- resolves the exact reachable candidate and committed tree in the canonical
  object store;
- recomputes the canonical source diff when a base exists;
- rederives the complete raw C1 resolution and bootstrap profile; and
- treats the isolated-clone diff only as a strict redundant cross-check.

For `base_unknown`, no diff or base is fabricated and reuse remains fresh-only.
Deterministic authority drift blocks before initial authority and is invalid
after initial authority. Unavailable or ambiguous authority is indeterminate.

The exact pre-spawn path for each check is:

1. validate all C2 public relationships and private prepared relationships;
2. perform the complete resolved-tool check;
3. call C2 `capture_before(check_id)`;
4. perform the final expensive canonical-source/C1/diff checkpoint;
5. call C2 `assert_ready_to_spawn(check_id)` as the final complete seal;
6. perform one no-follow tool stat comparison and one pure in-memory spawn
   vector digest; and
7. call `Popen` immediately with the frozen fields.

After step 5 there is no callback, Git or database operation, traversal,
manifest collection, or byte reread before `Popen`. Every successful
`capture_before` enters exactly one `reseal_after` branch, including spawn and
controller failures.

## Process and output semantics

C3 supports POSIX macOS and Linux. Each check starts a new session with
`shell=False`, closed file descriptors, null stdin, and stdout/stderr pipes.
One selector loop drains both streams in fixed 64 KiB reads. Timeout,
cancellation, or descendant cleanup sends TERM to the process group, waits one
second, sends KILL when needed, reaps the leader, drains to EOF, and requires a
final `killpg(..., 0)` ESRCH observation. EPERM, a live group, incomplete EOF,
or an unreaped leader makes quiescence indeterminate.

Checks run serially in verification-profile order. The exact completed prefix
is recorded and every remaining check is the exact `not_run_check_ids` suffix.
Verdict precedence is:

```text
invalid > indeterminate > blocked > spawn_failed > timed_out > cancelled > failed > passed
```

Each stream retains at most the smaller of its C2 cap and 1 MiB, while all
bytes are drained. A committed stream exposes canonical base64, exact byte
count, and byte digest. Any profile overflow, 1 MiB public-ceiling overflow,
incomplete EOF, secret-shaped environment, or fixed secret-pattern match makes
the stream uncommitted. An uncommitted stream exposes only fixed reason codes:
no bytes, count, raw digest, or secret-derived digest. It forces fresh-only and
withholds positive handoff, but it does not change a successful process exit
into a failed execution verdict.

Failures request `retain_failure` on the exact C2 lease. The runtime never
cleans retained roots. Duplicate callers for the same live workspace share one
current-process attempt and cannot spawn twice; the private workspace identity,
not a public or uncommitted digest, is the key.

## Current proof

Current proof applies to a Feature target or a Task linked to a Feature. A
standalone Task yields the exact `not_applicable` snapshot and may remain a
suitability candidate. Each start/end observation opens a separate SQLite URI
`mode=ro` connection, enables `query_only`, starts a deferred transaction, and
reads the event high-watermark first only to pin the snapshot. It rolls back
and closes in `finally`; C3 never opens either PCL lock.

The Feature snapshot contains only conclusive Feature status, selected
acceptance Evidence identity/type/content, supersession, the single canonical
recording event, the composite acceptance-link identity, and sorted fixed
health codes. The exact domains are:

```text
link_identity_sha256 = proof_document_sha256({
  "contract_version": "proof-current-feature-link-identity/v1",
  "evidence_id": evidence_id,
  "target_type": "feature",
  "target_id": feature_id,
  "link_role": "acceptance"
})

evidence_content_sha256 = proof_document_sha256({
  "contract_version": "proof-current-feature-evidence-content/v1",
  "manifest_sha256": "sha256:" + sha256(exact_manifest_bytes),
  "members": [{
    "metadata_sha256": proof_document_sha256({
      "contract_version": "proof-current-feature-member-metadata/v1",
      "metadata": exact_member_metadata
    }),
    "resolved_sha256": "sha256:" + sha256(exact_copied_member_bytes)
  }, ... in manifest order]
})

recording_event_sha256 =
  "sha256:" + sha256(canonical_event_bytes(canonical_event_record(row)))

proof_sha256 = proof_document_sha256({
  "contract_version": "proof-current-feature-snapshot-digest/v1",
  "snapshot": exact_snapshot_preimage
})
```

The digest excludes the observation HWM, unrelated rows/events, database path
and filesystem metadata, observation time, mutable timestamps outside the
canonical recording event, Evidence paths/commands/summaries, and runtime
fields. Therefore unrelated HWM advance is unchanged. A relevant Feature,
Evidence, link, recording-event, or copied-byte change yields `changed` and is
withheld. An unavailable or structurally inconclusive observation yields
`indeterminate`, null digest, and is withheld. A later anchoring stage must
repeat current-proof validation.

## Effect-zero and C4 boundary

C3 adds no public CLI, SQLite schema change, migration, dependency, database
write, Evidence/event/outbox record, render/dashboard write, terminal or
lifecycle mutation, persistence, anchor, or reuse authorization. C4 remains
responsible for semantic role/canary coverage and any parallel join. C3 only
runs the frozen structural profile.

## Accepted limitations

1. POSIX macOS/Linux only.
2. Repository isolation is not an OS, filesystem, or network sandbox.
3. Canonical-source validation, final workspace sealing, and kernel exec cannot
   be one atomic operation; the documented scheduling races remain.
4. Dynamic loaders, undeclared paths/services, and network inputs remain
   outside proof closure.
5. Original executable symlink-chain provenance remains only in memory and is
   neither execution-revalidated nor recoverable from later public anchoring.
6. A descendant can escape by creating a new session/process group.
7. Host crash, `SIGKILL`, or `os._exit` can lose the bundle and leave a process
   or lease.
8. Idempotency is current-process/current-workspace only.
9. Fixed secret scanning may miss unknown secret formats; minimal control-flow
   facts remain visible for secret-bearing checks.
10. Retained failure roots may accumulate pending separately authorized
    recovery.
11. Uncommitted-output bundles are not byte-distinguishing, expose no
    diagnostic output, and are not anchorable.
12. C3's 256-check, 4096-character identifier, and 1 MiB public-stream bounds
    are narrower than some C2-valid inputs.
13. Fixed secret-shape false positives or any stream over 1 MiB can make an
    otherwise passing run non-anchorable.

No limitation is upgraded into a reuse or anchoring claim.
