# ADR-004: Finish-attempt recovery uses advisory lease markers plus existing Evidence authority — no normalized attempt store

- Status: **Proposed** (awaiting human acceptance gate; the author does not
  self-record Accepted, per the ADR-002 discipline)
- Date: 2026-08-23
- Origin: GitHub Issue #3 “[P1] Design durable and resumable finish attempts
  after process loss”; residual risks in
  `docs/plan-p1-finish-progress-compact-output.md` §10
- Companion design: `docs/design-finish-attempt-recovery-v1.md`
- Owners: Reliability / CLI runtime
- Decision gate: maintainer plus one independent reviewer (same gate shape as
  ADR-002)

## 1. Context

An actual `pcl finish --emit-packet` run executes for minutes with **zero
durable state until all checks finish** (verified at `origin/main@da59b06`:
check Evidence commits first, then the packet/attempt commit; both after the
entire check loop). If the parent dies mid-run, operators cannot see that an
attempt existed, cannot classify it as live/stale, and get no recovery
guidance. Post-commit loss is already recoverable through existing surfaces.

The open architectural question: does recovering this visibility require a
normalized attempt store (new table, schema migration), or can existing
Evidence remain the sole authority while an additive advisory layer provides
liveness and guidance?

Constraints (from AGENTS.md and Issue #3): schema migrations and dependency
additions require explicit human approval; no daemon/coordinator/cloud;
`completion-packet/v2` requires a separate breaking-contract decision; prefer
the smallest local, dependency-light design; fail-closed behavior must prove
that process loss cannot fabricate a `COMPLETED_*` outcome or mutate targets.

## 2. Decision (proposed)

1. **Existing Evidence stays the only authoritative record of finish
   attempts**: `completion-packet/v1`, `finish-attempt/v1`, their Evidence
   rows/links/events, and target transitions are unchanged. No new identity
   competes with `cp-sha256:*` / `fa-sha256:*`.
2. **Add an advisory lease-marker layer**
   (`finish-lease-marker/v1`, content-frozen in the companion design §4):
   small JSON files under `.project-loop/finish-attempts/`, created
   O_EXCL+fsync before check execution, heartbeated atomically during the
   run, unlinked after outcome commits on every orderly exit.
3. **Classification is computed read-only at inspect time**
   (`pcl attempts inspect`, contract `finish-attempt-inspect/v1`) from marker
   bytes, heartbeat TTL, boot-id/PID probes, deterministic correlation to
   committed records, and dangling check-Evidence queries. It never mutates
   state.
4. **Retirement is explicit and event-audited**:
   `pcl attempts discard` refuses live/indeterminate markers, appends one
   additive `finish_attempt_discarded` event through the transactional outbox,
   then unlinks; idempotent on residue.
5. **No schema migration, no new table, no new dependency, no
   `completion-packet/v2`.** The one DB-visible addition is the new additive
   event type, which follows established practice (`finish_attempt_recorded`
   was itself added additively).

## 3. Rationale

- **Authority placement**: the start of an attempt is not completion proof.
  Normalizing it would put non-proof into the authoritative store, requiring
  compensating writes from processes that may no longer exist — a second
  lifecycle to operate, with orphan states mirroring the problem being solved.
- **Migration cost/benefit**: a migration needs the human approval gate,
  binary/database version-skew handling, and rollback planning, to buy query
  capability that a directory scan + indexed evidence-link queries already
  provide at local scale (bounded listing, single writer, single machine).
- **Fail-closed by construction**: markers participate in zero completion
  decisions (enforceable via import-boundary tests). Every ambiguous signal
  blocks *starting* work; none permits recording outcomes. The invariant “no
  false terminal outcome” is preserved structurally, not by convention.
- **Consistency with repo doctrine**: per-transaction locks (no long-held
  flocks), no silent deletes (explicit discard events instead of GC),
  display-only suggested commands, additive event types as compatible
  evolution.

## 4. Consequences

- Positive: pre-commit process loss becomes visible and classifiable;
  same-target concurrent finishes serialize safely; dangling check Evidence
  (already reachable today via readiness drift) becomes observable; all of it
  ships without a migration.
- Negative: classification depends on wall-clock heartbeat age with PID/boot
  fallbacks (conservative failure direction documented); a power-loss window
  between marker create and fsync degrades one run to status-quo
  invisibility; residue cleanup is manual-but-bounded (`discard --stale`,
  audit anomaly) rather than automatic.
- Deferred triggers for revisiting this decision: multi-host coordination,
  programmatic lease APIs consumed by external schedulers, or evidence that
  marker-scan inspection cost matters at project scale. Any of these warrants
  a successor ADR proposing normalized storage with its own migration plan.

## 5. Rejected alternatives (summary)

| Alternative | Primary rejection reason |
|---|---|
| Normalized `finish_attempts` table + migration | Approval-gated cost; stores non-proof authoritatively; new orphan-row lifecycle |
| SQLite start-event as the sole tracker | Dead writers leave forever-open rows or require stranger-written compensations |
| Whole-run flock lease | Contradicts per-transaction lock doctrine; crash hides intent |
| Mid-flight check resumption | Ephemeral isolated clone makes honest resumption impossible |
| Automatic stale-attempt retry/reap | Explicit issue non-goal; retirement stays human-triggered |
| Lease tokens inside packets | Forces `completion-packet/v2`; correlation achieves the value read-only |

## 6. Acceptance checklist for the human gate

- [ ] Authority boundary accepted (Evidence-only truth, advisory leases).
- [ ] Fail-closed proof outline (companion design §10) judged sufficient.
- [ ] Additive `finish_attempt_discarded` event acceptable without migration.
- [ ] Soft-lease refusal semantics (§7.4 of the design), including its
      observable behavior change versus today’s wasteful races, accepted.
- [ ] Implementation task breakdown (`agent-tasks/0227`) approved or amended
      before any implementation starts.
