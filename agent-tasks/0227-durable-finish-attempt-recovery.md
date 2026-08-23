# 0227 — Durable and resumable finish attempts after process loss

Status: **blocked on design-gate acceptance** (ADR-004 +
`docs/design-finish-attempt-recovery-v1.md`). Do not start any sub-task
before the human gate records acceptance.

Priority: P1 · Milestone: post-v0.6.0 · Origin: GitHub Issue #3

## Problem

`pcl finish --emit-packet` runs for minutes with no durable state until every
check completes. Parent loss leaves operators unable to see, classify, or
safely recover an attempt; readiness drift can already strand committed check
Evidence invisibly today. The accepted design adds an advisory lease-marker
layer plus read-only inspection and event-audited retirement, without a
migration and without changing completion semantics.

## Scope

Implement exactly the frozen contracts in
`docs/design-finish-attempt-recovery-v1.md`: `finish-lease-marker/v1`,
`finish-attempt-inspect/v1`, `finish-attempt-discard/v1`,
`finish_attempt_discarded` event, soft-lease refusal
(`finish_attempt_lease_live`, `finish_attempt_indeterminate`),
fail-closed marker creation (`finish_lease_unavailable`), and the fault-point
set listed in design §12.1.

## Invariants — what to protect

- Completion decisions never read lease state: outcomes/transitions remain
  exclusively inside the existing validated `BEGIN IMMEDIATE` commits with
  freshness re-checks (design §10 T1–T4).
- Outcome commits precede marker unlink; marker creation precedes check
  execution; marker-create failure aborts before execution.
- No-flag finish stdout JSON gains zero new fields from leasing; exit codes
  unchanged except the two new pre-start refusals and the B0′ typed abort.
- `--dry-run` and planner-mode finish create no markers; different-target
  concurrency is never blocked.
- No migration, no new dependency, no daemon, no packet/attempt contract
  change; sanitization rules identical to `finish-progress/v1`.
- No silent deletes: residue is classified and retired only via audited
  discard.

## Non-scope

Mid-flight check resumption; automatic retry/reap; MCP tools; `pcl next`
routing hints beyond cut-line task T-H2; consolidating the two finish commit
transactions; Windows support (runtime already requires `fcntl`).

## Sub-tasks (independently reviewable; each lands with its own tests)

### T-A Contracts, schemas, fixtures — runtime-free

Files: `src/pcl/contracts/schemas/finish-lease-marker-v1.schema.json`,
`finish-attempt-inspect-v1.schema.json`, `finish-attempt-discard/v1`
validator module(s) under `src/pcl/contracts/`, fixture seeds under
`tests/fixtures/`.

Deliver: schemas (`additionalProperties: false`), Python validators in the
existing fail-closed style, PF-1…PF-8 / NF-1…NF-9 fixture data, packaged-
contract wheel/sdist assertions following the
`completion-packet-v1.schema.json` pattern. Acceptance: schema validation
tests green; full suite unaffected.

### T-B Lease-marker module

New `src/pcl/finish_lease.py`: create (O_EXCL + fsync file/dir, collision
retry-once), atomic heartbeat rewrite (tmp + `os.replace`), unlink,
boot-id/PID probes, classification inputs, injected clock/filesystem for
tests. Fault points `finish_lease_before_marker_write`,
`finish_lease_after_marker_create`, `finish_lease_mid_heartbeat_replace`.
Acceptance: unit tests cover every boundary table row B0–B2 and both
refusal-relevant probes; constants not exposed as CLI flags.

### T-C Wire leasing into `emit_finish_packet`

Files: `src/pcl/finish_execution.py`. Create strictly after the idempotent
short-circuit/blocked-check gates and strictly before stage-dir/workspace
preparation; ticker thread mirroring `FinishProgressReporter` mechanics
(30 s cadence, bounded join, swallowed-and-counted failures); unlink after
outcome commits in the existing finally scope; B0′ typed abort
`finish_lease_unavailable`; soft-lease same-target refusal
(NF-3/NF-6 fixtures). Fault point `finish_lease_after_check_evidence_commit`.
Acceptance: no-progress baseline shape byte-identical; dry-run/planner create
no markers; F9/F10 concurrency cases pass.

### T-D `pcl attempts inspect`

Parser noun group (pattern of `audit`), read-only handler, classifier per
design §5/§6.4 (identity → temporal → ambiguous correlation; dangling
check-Evidence query bounded to 100). Exact-JSON tests against PF-1…PF-8;
corrupt/unknown-version markers classify `unreadable` (NF-1/NF-2); exit
semantics per §6.2. Acceptance: command opens read-only connections only
(assertable via test double); no projector flush.

### T-E `pcl attempts discard`

Event-first ordering through the service layer + outbox
(`finish_attempt_discarded` additive payload per design §6.3), then unlink;
idempotent residue cleanup via target-bounded prior-event scan; live/
indeterminate refusals; bulk `--stale` form; redaction + 500-char reason cap
(NF-8). Fault point `finish_attempt_discard_after_event_commit`. Acceptance:
discard-twice returns `changed:false` with no duplicate event; validate/render
green with the new event type present.

### T-F Failure-injection and concurrency suite

Extend `tests/test_crash_concurrency.py` with the six design-§12.1 fault
points (abrupt subprocess exits, barrier-synchronized races, no sleeps):
durable-state assertions at B0–B6; N-writer same-target O_EXCL race;
different-target pairing. Required on Linux per existing suite policy.
Acceptance: suite timing-independent; audit check clean-or-classified after
every injected death.

### T-G Audit anomaly + documentation

`stale_finish_attempt_marker` / unreadable-marker anomalies under
`human_review` in `pcl audit check` (report-only, no delete), scoped-check
compatible; docs: `docs/finish.md` leasing section, recovery-playbook routing
row, data-model note, release-notes fragment. Acceptance: audit tests cover
residue/unreadable classification; docs cross-link ADR-004 and the design.

### T-H Cut-line items (drop without blocking acceptance)

- T-H2: `pcl next` hint when a routed target has a live/indeterminate marker.
- T-H3: MCP `attempts_inspect` tool over the frozen JSON contract.

## Acceptance criteria (whole task)

- [ ] All frozen contracts from the design doc implemented with positive and
      negative fixtures passing.
- [ ] Design §10 proof assertions (T1–T4) exist as executable tests.
- [ ] Full gate green on every sub-task commit: `PYTHONPATH=src pytest`,
      `ruff check .`, `pcl validate --strict --json`, `pcl render --json`.
- [ ] No migration added; `pcl migrate status` unchanged for existing
      projects; old-binary compatibility notes updated if needed.
- [ ] Backward-compat statement verified by tests: no-progress finish result
      byte-shape unchanged except documented refusals.
