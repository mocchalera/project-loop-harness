# Local Proof-Anchor Drift Eligibility v1

P1-C C6 adds one internal, read-only predicate that compares a durable C5
proof-admission anchor with a freshly reconstructed C1-C4 basis. The result is
an observation at one pinned snapshot. It is not Evidence or authorization,
and it cannot authorize check execution, check skipping, result substitution,
terminal readiness, lifecycle transitions, mandatory Evidence, promotion,
publication, deployment, network access, or telemetry.

The authority firewall is absolute: a C6 receipt has `direct_input_right=false`,
`check_skip_authorized=false`, and `result_substitution_authorized=false` in
every status. Future consumers must start from a separately authorized input
and authority model, re-resolve current C5 and live authority, and must not use
the serializable C6 receipt as a capability.

## Authority and precedence

The caller supplies an anchor event assertion, expected Task, candidate, and
basis digest. These values are assertions, not authority. C6 resolves the
append-only C5 event first, then classifies authority for the event-derived
Task and basis in this order:

1. an invalid or multiple exhaustion tombstone is corrupt authority;
2. exactly one valid tombstone is unavailable and binds its write-time
   generation-3 witness;
3. with no tombstone, a valid unhealthy generation-3 head is exhaustion
   pending, before chain corruption or parallel-chain classification;
4. a missing anchor assertion is unavailable;
5. malformed, forked, gapped, or quartet-corrupt history is invalid;
6. multiple valid chains are invalid;
7. one valid chain supplies its current head.

An unhealthy generation 0-2 head is `anchor_recovery_required`; C6 does not
perform or advance recovery. A valid tombstone witness has `chain_head=null`
because C6 does not enumerate current chains on that path. Otherwise
`chain_head=true` means the selected event is the head of its own enumerated
chain; uniqueness is read from `valid_chain_count`.

## Lock and snapshot

C6 is POSIX-only. It observes the existing `.project-loop/project.lock` with
`O_RDONLY|O_CLOEXEC|O_NOFOLLOW`, a non-blocking shared `flock`, and no create,
repair, exclusive fallback, or capability mint. Root, loop-directory, path,
and descriptor identities include type, device, inode, mode, uid, and gid;
the lock must also be a single-link regular file with exact mode `0600` owned
by the effective uid. Identity is checked before and after acquisition and
again before the receipt is returned.

SQLite is opened through `mode=ro`, `query_only=ON`, and `BEGIN`. The first
metadata/HWM query pins one schema-8 snapshot, which is retained through C5
authority reads, current-proof capture, live C1-C4 reconstruction, canonical
comparison, and the final lock check. Only DELETE rollback-journal mode is
accepted. C6 never opens read-write, retries, repairs a journal, or accepts
WAL. The retained read transaction can delay a concurrent writer commit up to
that writer's timeout; callers therefore keep the internal evaluation bounded,
and no default/public consumer is enabled.

Python 3.10-compatible SQLite mapping uses safe `getattr` metadata and numeric
comparison, never version-dependent constants or raw message parsing:

| Numeric code | Classification |
|---:|---|
| 776 `SQLITE_READONLY_ROLLBACK` | `drift_database_recovery_required` |
| 264 `SQLITE_READONLY_RECOVERY` | `drift_database_recovery_required` |
| 520 `SQLITE_READONLY_CANTLOCK` | `drift_snapshot_unavailable` |
| base 5/6 BUSY/LOCKED | `drift_snapshot_unavailable` |
| base 11/26 CORRUPT/NOTADB | `drift_database_recovery_required` |

An `OperationalError` without usable metadata is conservatively classified as
recovery-required. Other SQLite errors are snapshot-unavailable unless the
corruption family is known. Mapping is total and sanitized. `KeyboardInterrupt`,
`SystemExit`, and `GeneratorExit` are never swallowed.

## Contract and effects

`proof-anchor-drift-eligibility/v1` is a closed Draft 2020-12 application
schema. Every nested object rejects unknown fields. Canonical JSON is UTF-8,
sorted-key, compact, `allow_nan=false`, and has no trailing newline. Digests
use:

```text
SHA256("pcl:" + domain + NUL + canonical_json(value))
```

The subject and receipt domains are `proof-anchor-drift-subject/v1` and
`proof-anchor-drift-eligibility/v1`. The receipt cap is 131,072 bytes; subject
cap 16,384; public identifier cap 4,096 UTF-8 bytes; reasons 32; participants
256; total checks 4,096; anchor rows 64 (`LIMIT 65`); tombstones use `LIMIT 2`.
The public-ID pattern intentionally follows the wider C5 pattern (including
colon), because C6 projects already validated C5 identifiers.

Hard failures return no receipt and expose only one of 13 closed codes plus a
phase from `preflight`, `lock`, `snapshot`, `authority`, `live`, `receipt`, or
`cleanup`. Raw paths, SQLite/Git messages, OIDs, actors, reports, process IDs,
inode/device values, retained roots, and leases are never returned.

Live reconstruction observes the C4 admission before applying C5's anchoring
eligibility guard. A determinate `coverage_live_identity_mismatch` is therefore
returned as `withheld` / `mismatched` / `live_execution_binding_changed`.
Current-proof or authority-provider indeterminacy is returned as `withheld` /
`unavailable` / `live_chain_unavailable`; Git or object-tool currentness
indeterminacy is returned as `withheld` / `indeterminate` /
`live_reconstruction_indeterminate`. This ordering prevents those three soft
observations from being collapsed into the generic receiptless
`proof_anchor_admission_withheld` mapping. Snapshot-required and other internal
invariant failures remain receiptless, sanitized hard errors.

C6 keeps SQLite schema 8, migration 0, dependency 0, Python requirement
unchanged, authoritative database/filesystem writes 0, Evidence/link/event/
outbox writes 0, checks executed/skipped/substituted 0, terminal/lifecycle 0,
mandatory Evidence/promotion 0, public CLI/MCP 0, and network/telemetry/
publication 0. Filesystem reads may affect only non-authoritative atime or page
cache state and are excluded from verdicts and digests.

The standing terminal rule remains Feature done plus healthy current Evidence.
Computed C3/C4/completion-policy verdicts remain authoritative; C6 never rounds
`prototype`, `needs_work`, `blocked`, `evidence_insufficient`, `indeterminate`,
or any non-passed verdict into eligibility.

## Retained limitations

- Live C2/C3 objects are intentionally not portable; their loss is a
  fail-closed availability limit.
- Git/object-store observations are not part of SQLite's atomic snapshot and
  remain protected by C4 two-pass currentness plus final exact comparison.
- The read transaction can delay non-exclusive SQLite writers.
- Private C5 issuer capability history is trusted at write time and cannot be
  reconstituted from serialized state.
- Filesystem reads may change non-authoritative atime/page-cache state.
- Receipts carry no freshness grant and have no consumer rights.
- Python 3.10 without SQLite error metadata conservatively collapses some
  contention into recovery-required.

These limitations grant no authority and do not authorize C7 or any later
consumer.
