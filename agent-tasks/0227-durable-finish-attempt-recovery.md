# 0227 — Durable and resumable finish attempts after process loss

Status: **blocked on design-gate acceptance** (ADR-004 rev 3 +
`docs/design-finish-attempt-recovery-v1.md` rev 3, final candidate). Do not start any
sub-task before the human gate records acceptance.

Priority: P1 · Milestone: post-v0.6.0 · Origin: GitHub Issue #3

## Problem

`pcl finish --emit-packet` runs for minutes with no durable state until every
check completes; parent loss leaves nothing to inspect, and parent death does
not stop the check process group. Readiness drift can already strand
committed check Evidence invisibly. The accepted design adds advisory lease
markers plus one read-only inspection command — no enforcement, no DB
surface, no new exit codes.

## Scope

Implement exactly the frozen contracts in design rev 3 (final candidate):
`finish-lease-marker/v1` (incl. `child_pgid`, `parent_start_identity`,
`stage_dir`, `workspace_dir`, `target_source: explicit|resolved`),
`finish-attempt-inspect/v1`, the §5 liveness truth table, §7.4 unlink
ordering, §9 retention reporting (frozen fields incl. unreadable-marker
suppression), §6.3 fixture corpus with the identical
four-surface source/wheel/sdist packaging gate.

## Invariants — what to protect

- Outcomes/transitions remain exclusively inside existing validated
  `BEGIN IMMEDIATE` commits with freshness re-checks; no completion-decision
  module imports lease state.
- V1 adds zero DB writes/events, zero CLI behavior change to finish itself,
  no refusal paths, no migration/dependency.
- Marker unlink happens only at U1 (after outcome commit) or U2 (typed abort
  before first check spawn); never a `finally` blanket; post-start exceptions
  preserve the marker.
- Parent dead + child group alive ⇒ `indeterminate`; only positive proof that
  nothing runs yields retry-safe guidance.
- No per-token attribution of Evidence/outcomes; target-wide sections only.
- Degraded marker writes never abort a started run; sanitization identical to
  `finish-progress/v1`.

## Non-scope (deferred, each behind its own gate)

Per-target claim/election and refusal; marker-failure abort policy;
discard/cancel mutation + audit event; audit anomalies; authoritative token
anchors / per-token attribution; `pcl next` hints; MCP tools; consolidating
the two finish commit transactions.

## Sub-tasks and dependency graph

```text
T-A ──► T-B ──► T-C ──► T-F
  │             T-C ──► T-D ──► T-E
  │                        └──► T-F
  └───────────────────────────▲  (E also needs A)
```

Each sub-task lands alone, green under the standard gate (`PYTHONPATH=src
pytest`, `ruff check .`, `validate --strict --json`, `render --json`).

### T-A Contracts, schemas, fixture corpus — runtime-free

Files: `src/pcl/contracts/schemas/finish-lease-marker-v1.schema.json`,
`finish-attempt-inspect-v1.schema.json`, validator modules under
`src/pcl/contracts/`, corpus seeds under
`tests/fixtures/finish-attempts-corpus/` (PF-1…PF-12, NF-1…NF-7 inputs +
expected payloads). Depends on: none. Acceptance: validators fail closed
with path-addressed errors; schemas packaged via the existing
`contracts/schemas/*.json` glob.

### T-B Lease-marker module

New `src/pcl/finish_lease.py`: create (O_EXCL + fsync file/dir, collision
retry-once), atomic heartbeat rewrite (tmp + `os.replace`) carrying
`child_pgid`, unlink helpers for U1/U2 call sites, boot-id/pid/start-identity/
pgid probes, truth-table classifier, injected clock/filesystem. Fault points
FP-1…FP-3. Depends on: T-A. Acceptance: unit tests enumerate every §5 gate row and matrix cell;
degraded-create path proven non-fatal.

### T-C Wire markers into `emit_finish_packet`

Create at the §7.1 point; heartbeat ticker mirroring `FinishProgressReporter`
mechanics (30 s cadence, bounded join, swallowed failures) fed by the frozen
`on_spawn(pgid)` post-spawn callback contract (§7.3); explicit U1 unlink
after successful outcome commit and U2 unlink in the typed pre-spawn abort
branch; degraded create failure (FP-1); post-start exceptions preserve the
marker (FP-6/NF-5). Depends on: T-B.
Acceptance: no-progress baseline byte-shape unchanged; dry-run/planner create
no markers; concurrency case yields two independent same-target markers.

### T-D `pcl attempts inspect`

Parser noun group (pattern of `audit`), read-only handler: truth-table
classification with `truth_table_row` echoed, target-wide
`uncommitted_check_evidence` + `committed_outcomes` sections, retention
report, bounds/truncation/filter rules. Depends on: T-C (real residue to
inspect). Acceptance: PF/NF corpus green from source; read-only connection
assertable; no projector flush.

### T-E Identical-corpus packaging gate

Build wheel + sdist, run the same corpus on all four surfaces — source,
installed wheel, installed sdist, extracted-and-run sdist; byte-compare after
the two declared normalizations (`generated_at`, `heartbeat_age_seconds`);
assert schema files present in wheel and sdist. Depends on: T-A, T-D.
Acceptance: four-surface byte-identical results in CI-runnable form.

### T-F Failure-injection suite

Extend `tests/test_crash_concurrency.py` with FP-4/FP-5/FP-7 subprocess
abrupt exits plus FP-1/FP-3 injections and the barrier-synchronized
same-target / different-target concurrency cases. Depends on: T-C, T-D.
Acceptance: timing-independent; audit check clean after every injected death;
L-boundary durable states match §7.5; PF-10 proves null-pgid parent death is
never retry-safe.

## Acceptance criteria (whole task)

- [ ] All frozen contracts implemented with PF/NF fixtures passing and the
      four-surface packaging gate green.
- [ ] Design §10 proof assertions exist as executable tests.
- [ ] Full gate green on every sub-task commit; no-progress finish result
      byte-shape unchanged.
- [ ] No migration added; `pcl migrate status` unchanged for existing
      projects.
- [ ] Docs shipped: `docs/finish.md` marker note, recovery-playbook operator
      flow (inspect → resolve children → verified cleanup → retry),
      release-notes fragment.
