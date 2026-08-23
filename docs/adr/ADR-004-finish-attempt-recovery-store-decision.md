# ADR-004: Finish-attempt recovery uses advisory lease markers plus existing Evidence authority — no normalized attempt store

- Status: **Proposed** (awaiting human acceptance gate; the author does not
  self-record Accepted, per the ADR-002 discipline). Revision 2: tightened by
  the Sol xhigh design review — v1 is advisory-only with zero enforcement,
  zero DB surface, and zero new exit codes.
- Date: 2026-08-23
- Origin: GitHub Issue #3; residual risks in
  `docs/plan-p1-finish-progress-compact-output.md` §10
- Companion design: `docs/design-finish-attempt-recovery-v1.md` (rev 2)
- Owners: Reliability / CLI runtime
- Decision gate: maintainer plus one independent reviewer (same gate shape as
  ADR-002)

## 1. Context

An actual `pcl finish --emit-packet` runs for minutes with zero durable state
until all checks finish. Parent loss leaves operators unable to see or
classify an attempt, and — because each check child runs in its own process
group (`start_new_session: True`, `guarded_process.py@da59b06`) — parent
death does not even prove the attempt’s work has stopped. Post-commit loss is
already recoverable through existing surfaces.

The architectural question: does recovering this visibility require a
normalized attempt store and migration, or can existing Evidence remain the
sole authority behind a strictly additive advisory layer?

Constraints (AGENTS.md, Issue #3): migrations and dependency additions are
approval-gated; no daemon/coordinator/cloud; `completion-packet/v2` needs a
separate breaking-contract decision; fail-closed behavior must make it
impossible for process loss to fabricate a `COMPLETED_*` outcome.

## 2. Decision (proposed)

1. **Existing Evidence stays the only authoritative record**: packets,
   `finish-attempt/v1`, Evidence rows/links/events, target transitions — all
   unchanged. No competing identity.
2. **Add an advisory lease-marker layer** (`finish-lease-marker/v1`,
   content-frozen in design §3.1): small JSON files under
   `.project-loop/finish-attempts/`, created O_EXCL+fsync before check
   execution, heartbeated atomically (including the current child pgid),
   unlinked only after an authoritative outcome commit or a typed abort
   before the first check spawn.
3. **One read-only command**, `pcl attempts inspect`
   (`finish-attempt-inspect/v1`), classifies markers through a frozen,
   exhaustive liveness truth table (design §5) in which parent death without
   proof the child group is gone is `indeterminate`, never retry-safe.
   Inspection also reports **target-wide** dangling check Evidence and newest
   committed outcomes, never attributed to a specific token (no authoritative
   token anchor exists).
4. **V1 adds zero SQLite surface**: no events, no rows, no schema change, no
   dependency, no new exit codes, no enforcement, no refusal. Marker-write
   failure degrades to status-quo invisibility rather than aborting the run.
5. **Retention is numeric and operator-executed** (design §9: markers 14 d /
   50-count; temp artifacts 7 d; documented verified cleanup commands); PLH
   ships no destructive automation.

## 3. Rationale

- Start-of-attempt is not completion proof; normalizing it would place
  non-proof in the authoritative store and require dead processes’ state to
  be closed by strangers. Advisory files need no lifecycle owner.
- Per-token O_EXCL cannot elect a winner between concurrent finishes, and
  scan-then-create election is TOCTOU-unsound — so v1 claims nothing and
  refuses nothing. Mutual exclusion returns later only behind a genuinely
  atomic claim mechanism, together with the marker-abort policy that only
  makes sense once enforcement exists.
- Fail-closed direction survives simplification: every ambiguous signal
  (`indeterminate`, `unreadable`, degraded marker writes) reduces
  information; `stale_interrupted`/retry-safe guidance requires positive
  proof that neither parent nor child group is running.
- Zero DB surface means no event-vocabulary churn, no projector load, no
  migration gate — strictly smaller than any alternative that touches SQLite.

## 4. Consequences

- Positive: pre-commit loss becomes visible and classifiable; child-group
  liveness is explicit; dangling check Evidence (already reachable today via
  readiness drift) becomes observable; ships without migration or behavior
  change beyond one additive read-only command.
- Negative: classification depends on wall-clock heartbeat age with
  boot/pid/pgid fallbacks (conservative direction enforced by truth table);
  residue cleanup is manual-but-bounded; concurrent same-target finishes
  remain possible and merely visible.
- Revisit triggers: multi-host coordination; programmatic consumers needing
  per-target mutual exclusion; token↔outcome attribution requirements
  (authoritative anchor ⇒ packet-contract decision). Each warrants a
  successor ADR.

## 5. Rejected / deferred alternatives

| Alternative | Verdict | Reason |
|---|---|---|
| Normalized `finish_attempts` table + migration | rejected | approval-gated cost; stores non-proof authoritatively; orphan-row lifecycle |
| SQLite start-event tracking | rejected | dead writers leave forever-open rows needing stranger-written compensation |
| Scan-then-refuse same-target leasing (rev-1) | **rejected in rev 2** | TOCTOU race: two scanners both pass; per-token O_EXCL elects nothing |
| Fail-closed marker-create abort (rev-1) | **deferred** | disproportionate without enforcement value |
| Discard/cancel mutation + audit anomaly + bulk form (rev-1) | **deferred** | retirement semantics belong with a real claim mechanism; v1 cleanup is documented operator action |
| Whole-run flock lease | rejected | contradicts per-transaction lock doctrine; crash hides intent |
| Mid-flight check resumption | rejected | ephemeral isolated clone makes honest resumption impossible |
| Automatic stale-attempt retry/reap | rejected | issue non-goal |
| Lease tokens inside packets | deferred | forces `completion-packet/v2`; read-time target-wide reporting covers v1 |

## 6. Acceptance checklist for the human gate

- [ ] Authority boundary accepted (Evidence-only truth; advisory markers).
- [ ] V1 scope accepted: advisory + read-only inspect only; enforcement,
      discard, audit integration explicitly deferred (§5).
- [ ] Liveness truth table (design §5), including the child-group rule
      (retry-safe requires reboot proof or a non-null recorded pgid probed
      absent) and the gate/matrix precedence, judged sound.
- [ ] Numeric retention bounds and operator-executed cleanup accepted.
- [ ] Task breakdown (`agent-tasks/0227`) approved before implementation.
