# Design: Durable and Resumable Finish Attempts After Process Loss

Status: **Proposed — design-gate candidate for Issue #3** (revision 2,
addressing the Sol xhigh design review). Implementation must not start before
the ADR and this design are accepted (`agent-tasks/0227-durable-finish-attempt-recovery.md`).

Date: 2026-08-23 (rev 2) · Base: `origin/main` @ `da59b068f27becdc6a8bc857709f899787326638`

Origin: GitHub Issue #3; residual risks in
[`docs/plan-p1-finish-progress-compact-output.md`](plan-p1-finish-progress-compact-output.md)
§10. Companion decision:
[`docs/adr/ADR-004-finish-attempt-recovery-store-decision.md`](adr/ADR-004-finish-attempt-recovery-store-decision.md).

## 1. Problem, verified against origin/main

An actual `pcl finish --emit-packet` runs for minutes with **no durable state
until every check finishes** (`src/pcl/finish_execution.py@da59b06`: check
Evidence commits first, then the packet/attempt commit). During that window:

1. Nobody can see that an attempt exists, or classify residue afterwards as
   live / interrupted / already-committed.
2. The `--progress` stream is ephemeral stderr; heartbeats die with the
   terminal.
3. **Children outlive the parent.** Each check child is spawned with
   `start_new_session: True` and its pgid captured
   (`guarded_process.py@da59b06`). If the parent is killed mid-check, the
   child group keeps running. “Parent gone” therefore does **not** imply “the
   attempt’s work is done” — retry guidance issued on parent-death alone
   would be unsound.
4. Post-commit parent loss is already recoverable today (`pcl next --target`,
   `pcl evidence show`, idempotent packet matching). Pre-commit loss is
   invisible. Readiness drift can already strand committed check Evidence
   invisibly (`FinishTargetReadinessChangedError` rolls back only the outcome
   transaction).

## 2. Scope discipline (v1)

V1 is **advisory markers + read-only inspection, nothing else**:

- Zero DB writes, zero new events, zero new exit codes, zero enforcement.
- The default-shape finish stdout JSON gains no fields; existing exit codes
  and semantics are untouched.
- Multiple concurrent finishes may each create their own marker; there is no
  election, no refusal, no claim. Per-token O_EXCL cannot elect a winner and
  scan-then-create has a TOCTOU race, so any per-target mutual exclusion is
  **deferred** until an actually-atomic claim mechanism is designed.
- Discard/cancel commands, audit anomalies, `pcl next` hints, and MCP tools
  are deferred (§11). Retirement of residue is a documented operator action.

Invariants that must not change: outcomes/transitions occur only inside the
existing validated `BEGIN IMMEDIATE` commits with freshness re-checks;
nothing in this design participates in any completion decision path.

## 3. Attempt identity and the two-layer model

| Layer | Artifact | Authority |
|---|---|---|
| Committed record | `completion-packet/v1` / `finish-attempt/v1` content-addressed Evidence + links + existing events | Authoritative proof of what happened |
| Lease marker | `finish-lease-marker/v1` file under `.project-loop/finish-attempts/` | Advisory: proves someone started; proves nothing finished |

Authoritative identity stays `cp-sha256:*` / `fa-sha256:*`. In-flight runs get
an advisory token `FL-<16 hex>`, deliberately **not** embedded in packets.
There is deliberately **no persisted attempt state machine**: a dead writer
could never close its own persisted state. States below are computed
read-only at inspect time.

```text
run start ──► marker created (O_EXCL + fsync) ──► RUNNING (atomic heartbeats)
    │ orderly completion: outcome commits, THEN explicit unlink
    │ typed abort before first check spawn: explicit unlink
    ├─ anything else after start (exception, kill, power): marker PRESERVED
    ▼
RESIDUE → classified read-only: running_live | indeterminate |
          stale_interrupted | unreadable
```

**Attribution boundary:** v1 has no authoritative link between a token and
any Evidence row or committed outcome, so inspect never attributes dangling
Evidence or outcomes to a specific marker. It reports them **target-wide**
until an authoritative token anchor exists (e.g., a future packet field — a
`completion-packet/v1` contract change requiring its own decision; deferred).

### 3.1 Marker contract (`finish-lease-marker/v1`)

Path `.project-loop/finish-attempts/<target_type>-<target_id>-<token>.json`;
canonical UTF-8 JSON, sorted keys, compact separators, trailing newline;
schema `pcl/contracts/schemas/finish-lease-marker-v1.schema.json`,
`additionalProperties: false`, ≤ 4 KiB. Frozen fields:

```text
contract_version        "finish-lease-marker/v1"
token                   FL-<16 lowercase hex> (UUID4-derived; retry once on collision)
target                  {"type": "task"|"goal", "id": "T-NNNN"|"G-NNNN"}
target_source           "explicit" | "resolved"     (current routing vocabulary)
pid                     owning parent PID
parent_start_identity   platform process-start identity or null
                        (Linux /proc/<pid>/stat starttime; else unavailable)
boot_id                 current-boot identifier at create/heartbeat, or null
hostname                advisory machine name
started_at / heartbeat_at / heartbeat_count   RFC 3339 UTC + counter
phase                   planning|workspace_preparation|checks|
                        repository_snapshot|strict_validation|evidence_commit
check_index / check_count / check_config_keys public config keys only
child_pgid              pgid of the currently running check child, or null
timeout_seconds         per-check timeout for this run
stage_dir               basename of this run's .project-loop/tmp/finish-checks-* dir
workspace_dir           basename of this run's $TMPDIR/pcl-finish-workspace-* clone
plan_identity           {base_revision, head_revision, diff_sha256,
                        input_manifest_sha256}  — informational only in v1
pcl_version             producing runtime version
```

Sanitization inherits `finish-progress/v1` verbatim: no raw argv, no
environment values, no captured output, no secret-shaped strings. Unknown
`contract_version` or schema-invalid content classifies `unreadable`; never
guessed, never auto-deleted.

## 4. Failure matrix

| # | Disruptor | Today (@da59b06) | With this design | Inspect view |
|---|---|---|---|---|
| F1 | Terminal disconnect (SIGHUP/closed pipe) | Stream truncates | Marker residue unless orderly exit | Liveness table (§5) |
| F2 | Parent crash / `kill -9` / OOM mid-run | Nothing durable; possible dangling check Evidence | Marker preserved; **child group may still run** | `indeterminate` while pgid alive; `stale_interrupted` once provably gone |
| F3 | Host restart | Same as F2; temp clones cleared by OS | Stored boot-id mismatch proves restart; children cannot survive it | `stale_interrupted` (§5 row R5) |
| F4 | Child check exits nonzero / crashes | Guarded executor records failure; INCOMPLETE packet committed, exit 1 | Unchanged; marker unlinked after outcome commit | Historical packet lookup |
| F5 | Child check timeout | `timeout_recovery` steps → INCOMPLETE_VALIDATION packet | Unchanged | Existing `pcl next` route |
| F6 | Whole-run supervisor timeout (parent killed) | = F2 | = F2 | §5 |
| F7 | Stale residue found later | Undetectable | Classified + retention-reported; operator cleans per §9 | `stale_interrupted`/`unreadable` |
| F8 | Readiness drift between commits (non-crash) | Outcome tx rolls back; check Evidence dangles **invisibly, today** | Same rollback; inspect lists dangling rows | Target-wide listing (§6.3) |
| F9 | Concurrent finishes, same target | Both execute checks wastefully; commit-time freshness checks preserve correctness | Unchanged; both markers listed independently, no election | Two marker entries |
| F10 | Concurrent finishes, different targets | Works | Unchanged | Independent entries |
| F11 | Disk full/EACCES on marker write | n/a | **Degraded, not fatal:** run continues with status-quo invisibility (§7.2) | No marker |

## 5. Liveness classification — exhaustive truth table

Signals: `H` = heartbeat freshness (`now − heartbeat_at` vs TTL 120 s);
`B` = stored boot-id vs current boot-id; `P` = parent pid probe with
process-start identity when the platform exposes it (Linux `/proc/<pid>/stat`
starttime; elsewhere unavailable ⇒ `?`); `C` = recorded child-pgid probe
(`killpg(pgid, 0)`; empty between checks). Classification is advisory and
fail-closed: every ambiguity lands in `indeterminate`.

Constants (module-level, not flags):
`FINISH_LEASE_HEARTBEAT_SECONDS = 30`,
`FINISH_LEASE_STALE_AFTER_SECONDS = 120`,
`FINISH_LEASE_CLOCK_SKEW_SECONDS = 5`.

| Row | Marker readable | H (vs TTL) | B | P | C | State | Rationale |
|---|---|---|---|---|---|---|---|
| R0 | no | — | — | — | — | *(no marker)* | Nothing to classify; target-wide sections still apply (§6.2) |
| R1 | invalid JSON / bad schema / unknown version | — | — | — | — | `unreadable` | Never guessed; human review |
| R2 | yes | fresh (0 ≤ age ≤ TTL) | * | * | * | `running_live` | Writer demonstrably wrote ≤ TTL ago; overrides all other signals |
| R3 | yes | **future** (`age < −skew`) | * | * | * | `indeterminate` | Clock regression; refuse to trust |
| R4 | yes | stale | match | alive, identity matches | * | `indeterminate` | Owner alive but stopped beating (SIGSTOP/hang) |
| R5 | yes | stale | **mismatch** (restart proven) | n/a | n/a | `stale_interrupted` | Host restarted: parent and children both gone regardless of probes |
| R6 | yes | stale | match | dead | gone/none | `stale_interrupted` | Owner gone, no child work outstanding |
| R7 | yes | stale | match | dead | **alive** | `indeterminate` | Critical case: children may still be executing; never retry-safe |
| R8 | yes | stale | match | alive, **identity mismatch** (pid reused) | gone/none | `stale_interrupted` | Reuse proves original owner dead; children checked separately |
| R9 | yes | stale | match | alive, identity mismatch | alive | `indeterminate` | Original owner dead, child group outstanding |
| R10 | yes | stale | match | alive, identity `?` (platform) | * | `indeterminate` | Cannot exclude pid reuse |
| R11 | yes | stale | match | dead | none recorded (between checks) | `stale_interrupted` | Sequential checks: no child was running at last heartbeat |
| R12 | yes | stale | unknown on either side (stored null/corrupt **or** current unreadable/error) | gone (dead or reused) + C gone/none | — | `stale_interrupted` | Under either boot hypothesis (same boot: probes dead; prior boot: restart killed all) nothing runs |
| R13 | yes | stale | unknown on either side (stored null/corrupt **or** current unreadable/error) | alive or C alive | * | `indeterminate` | Something is running and identity is uncertain |

Rules behind the table (normative):

- Fresh heartbeat wins (R2) because only a live writer produces it.
- Restart proven (R5) short-circuits everything: processes cannot survive a
  reboot.
- Parent-death alone never yields `stale_interrupted` (R7/R9): the child
  group must be probed. Only the **last heartbeat’s** pgid is considered,
  and only within the same boot.
- Boot-id unknown (stored null/corrupt or current read error) collapses to
  the hypothesis union: if every plausibly-running thing is provably absent,
  `stale_interrupted`; otherwise `indeterminate` (R12/R13).
- `stale_interrupted` is the **only** state whose guidance may say
  “retrying finish is safe”; even then the guidance notes that a fresh run
  neither resumes nor cleans the old attempt (§7).

## 6. Frozen public contract: `pcl attempts inspect`

New top-level noun group (pattern of `audit`/`jobs` in `parser_control.py`);
the flag-heavy `finish` parser is untouched.

```text
pcl attempts inspect [--target T-XXXX|G-XXXX] [--json]
```

Read-only: read-only DB connection, no lock upgrades, no marker writes, no
event appends, no projector flush. Requires an initialized project (else exit
2). Exit `0` whenever the command ran; findings live in the payload; exit `2`
usage only. Contract: `finish-attempt-inspect/v1`; schema
`pcl/contracts/schemas/finish-attempt-inspect-v1.schema.json`
(`additionalProperties: false`). MCP exposure deferred.

### 6.1 Payload shape

```json
{
  "ok": true,
  "contract_version": "finish-attempt-inspect/v1",
  "generated_at": "2026-08-23T09:30:00Z",
  "filter": {"target": {"type": "task", "id": "T-0151"}},
  "counts": {"total": 2, "running_live": 1, "indeterminate": 1,
             "stale_interrupted": 0, "unreadable": 0},
  "attempts": [
    {
      "token": "FL-0f1e2d3c4b5a6978",
      "marker_path": ".project-loop/finish-attempts/task-T-0151-FL-0f1e2d3c4b5a6978.json",
      "state": "indeterminate",
      "truth_table_row": "R7",
      "target": {"type": "task", "id": "T-0151"},
      "started_at": "2026-08-23T09:00:00Z",
      "last_heartbeat_at": "2026-08-23T09:04:30Z",
      "heartbeat_age_seconds": 1520.4,
      "liveness": {"boot_id_match": true, "parent_pid_alive": false,
                   "parent_start_identity_verified": null,
                   "child_pgid_alive": true},
      "guidance": [
        {"code": "finish_attempt_child_group_alive",
         "message": "Parent is gone but the recorded check process group is still alive. Verify and stop it before treating this attempt as finished.",
         "command": null}
      ]
    }
  ],
  "uncommitted_check_evidence": [
    {"target": {"type": "task", "id": "T-0151"},
     "evidence_ids": ["E-0912", "E-0913"],
     "count": 2}
  ],
  "committed_outcomes": [
    {"target": {"type": "task", "id": "T-0151"},
     "kind": "completion_packet", "outcome": "INCOMPLETE_VALIDATION",
     "evidence_id": "E-0899",
     "created_at": "2026-08-22T17:44:03Z"}
  ],
  "retention": {
    "over_horizon_markers": ["FL-77ab01fe44cc9012"],
    "marker_count_total": 2,
    "stage_dirs_over_horizon": [],
    "cleanup": "Operator-only; see docs/design-finish-attempt-recovery-v1.md §9."
  },
  "truncated": false
}
```

### 6.2 Contract details

- Listing bounded to the 100 newest markers by `started_at`;
  `truncated: true` beyond that. `--target` filters all three sections and
  echoes the filter; unknown target IDs yield empty sections (predictable),
  not an error.
- Every attempt carries `truth_table_row` (§5) so classification is auditable
  against the frozen table.
- `guidance` records are display-only strings; PLH never executes them
  (repository doctrine for suggested commands).
- **Target-wide sections, never per-token**: `uncommitted_check_evidence`
  lists target-linked `verification_check` Evidence rows newer than the
  target’s last `completion_packet_created` / `finish_attempt_recorded`
  event (`LIMIT 100`, newest first). `committed_outcomes` lists the target’s
  newest packet/attempt from the existing evidence links. Neither names a
  token: no authoritative token↔artifact anchor exists in v1 (§3).
- `unreadable` entries carry the parse/schema error class, never raw contents.
- `retention` computes §9 bounds read-only; `cleanup` is a pointer to
  documentation, not an executable plan.

### 6.3 Frozen fixture corpus (positive/negative)

Seeded projects under `tests/fixtures/finish-attempts-corpus/`; each case =
input tree + expected payload JSON. Expected payloads normalize only
`generated_at` and `heartbeat_age_seconds` (declared volatile; injected
clock otherwise).

| ID | Setup | Expected |
|---|---|---|
| PF-1 | Live marker (fresh heartbeat, own pid) | `running_live` (R2) |
| PF-2 | Stale marker; pid dead; pgid gone | `stale_interrupted` (R6); retry-safe guidance |
| PF-3 | Stale marker; pid dead; **recorded pgid alive** (probe faked via holder process) | `indeterminate` (R7); child-group guidance; no retry-safe claim |
| PF-4 | Stale marker; pid alive but start-identity mismatches | R8/R9 split by pgid |
| PF-5 | Stale marker; `heartbeat_at` 60 s in the future | `indeterminate` (R3) |
| PF-6 | Stale marker; stored boot-id ≠ current | `stale_interrupted` (R5) |
| PF-7 | Two markers, same target, one live one stale | Both listed; counts correct; no election |
| PF-8 | Marker aged > 14 d + orphan-looking stage dir refs | `retention.over_horizon_markers` populated; cleanup is doc pointer |
| PF-9 | Committed packet + unrelated stale marker | Packet appears under `committed_outcomes`; marker classified on its own; **no linkage claimed** |
| NF-1 | Corrupt JSON marker | `unreadable`; exit 0 |
| NF-2 | Unknown `contract_version` | `unreadable` with version class |
| NF-3 | Uninitialized project | exit 2 usage |
| NF-4 | Marker create fails (injected ENOSPC) during finish | Run proceeds normally; result JSON unchanged; no marker left |
| NF-5 | Unexpected exception after first check spawn | Marker preserved (see fault point FP-6) |
| NF-6 | `inspect --target T-9999` (unknown) | Empty sections, exit 0 |

**Identical-corpus packaging gate:** the same corpus executes through the
CLI three ways — (a) source checkout (`PYTHONPATH=src`), (b) built wheel
installed into an ephemeral venv, (c) built sdist both installed and
extracted-and-run — and the three payload sets are byte-identical after the
two declared normalizations. Schemas ship via the existing
`contracts/schemas/*.json` package-data glob (`pyproject.toml`), asserted
present in wheel and sdist following the `completion-packet-v1.schema.json`
test pattern.

## 7. Lifecycle integration and ordering

### 7.1 Marker creation point

In `emit_finish_packet`, strictly **after** argument/config validation,
planning, the idempotent-completed-packet short circuit, and the blocked-check
gate — strictly **before** stage-directory creation, workspace preparation,
and any check execution. `--dry-run` and planner-mode finish never create
markers.

### 7.2 Create failure degrades, never aborts (rev-2 change)

If the marker cannot be written (ENOSPC/EACCES/O_EXCL loss), finish logs an
internal counter and continues with status-quo invisibility. Rationale: with
enforcement deferred, an advisory layer must not hold a ten-minute run
hostage to a filesystem hiccup. Runtime heartbeat-write failures likewise
degrade (caught, counted, gaps visible later as stale classification).
Fail-closed direction is preserved: degradation can only reduce visibility,
never fabricate proof or alter outcomes.

### 7.3 Heartbeat mechanics

A finish-local ticker mirrors `FinishProgressReporter` mechanics: injectable
clock/sink, bounded join (≤2 s) on every exit path, swallowed-and-counted
exceptions, no subprocess ownership. Updates land at check boundaries, phase
transitions, and the 30 s cadence; each check-start update records that
child’s `child_pgid` (available from the guarded executor) and clears it at
check-finish. Runs regardless of `--progress`.

### 7.4 Unlink ordering (normative; rev-2 change)

The marker is removed at exactly two explicit code points — **never in a
`finally` blanket**:

1. **U1 — after the authoritative outcome commit succeeds** (packet or
   attempt transaction returned committed): outcome-first ordering means a
   crash before unlink leaves marker + committed outcome, which inspect
   reports side-by-side without linking them.
2. **U2 — after a typed abort before the first check spawn** (e.g.,
   workspace-materialization `InvalidInputError`): nothing executed and
   nothing durable changed, so the marker would be pure noise.

Everything else after start — unexpected exceptions, `KeyboardInterrupt`,
signals, kills, readiness-drift rollbacks, `DataStoreError` — **preserves**
the marker: the honest state is “this attempt started and its fate is
unknown/partial”, which is exactly what inspection exists to show. Residue
persists until operator cleanup (§9); a later run manages only its own
token and never cleans predecessors.

### 7.5 Ordered boundary table

| Boundary | Crash here ⇒ | Convergence |
|---|---|---|
| L0 pre-marker validation failures | nothing (today’s behavior) | safe retry |
| L1 marker create fails | degraded continue; no marker | retry gives status quo |
| L2 after create/fsync | residue marker | classified per §5; operator cleanup |
| L3 during heartbeat rewrite (tmp + `os.replace`) | old or new bytes, never torn | classification deterministic |
| L4 after check-Evidence commit, before outcome commit | marker + dangling check Evidence | target-wide listing (F8/F-L4); retry creates new rows; historical rows remain honest history |
| L5 after outcome commit, before unlink | marker + committed outcome | reported side-by-side, unlinked only by operator |
| L6 during unlink | entry present or absent | both fine |

## 8. Relationship to existing proof surfaces

- **Check Evidence / incomplete-attempt Evidence / completion packets /
  terminal readiness**: producers and consumers unchanged; lost attempts
  produce no artifact — fabricating one post-mortem would forge proof.
  Markers are never referenced from packets.
- **Repository snapshots/idempotency**: markers live under `.project-loop/`,
  excluded from `diff_sha256` bytes and the `dirty` flag
  (`finish_repository.py@da59b06`); they surface only in the result’s
  `harness_local_state` presentation while in flight. Packet matching and
  race guards are unaffected.
- **Target binding**: markers mirror resolved `--task/--goal/--run` bindings
  using the current vocabulary `target_source: "explicit" | "resolved"`
  (explicit flags vs routing-target fallback, `finish_execution.py@da59b06`);
  implicit planner routing resolves identically before marker creation, so
  every marker is target-bound.
- **Recovery playbook**: documentation-only routing addition shipped with
  implementation (operator flow: inspect → resolve children → optional
  verified cleanup → retry).

## 9. Retention, privacy, and operator cleanup (numeric bounds)

All bounds are module constants (not flags); inspect reports them read-only.
PLH ships **no destructive automation** in v1 — cleanup is operator-executed,
with verification steps in the docs.

| Object | Location | Bound (default) | Verified cleanup |
|---|---|---|---|
| Lease markers | `.project-loop/finish-attempts/*.json` | age > **14 days** from `started_at`, or project total > **50** | `inspect` lists offenders (`retention`); operator confirms each is `stale_interrupted`/`unreadable` (never `running_live`/`indeterminate`), then deletes the listed paths (`rm .project-loop/finish-attempts/<file>`); `unreadable` requires human reading first |
| Check stage dirs | `.project-loop/tmp/finish-checks-*` | age > **7 days** (dir mtime) | Marker files record their `stage_dir` basename; operator cross-checks the name against live markers’ references before `rm -rf` |
| Isolated source clones | `$TMPDIR/pcl-finish-workspace-*` (system temp; outside the project) | age > **7 days** | Same reference check (clone root name recorded as `workspace_dir`); typically cleared by reboot; never auto-deleted |

Privacy/redaction: enumerated fields only; no argv, env values, output, or
secret-shaped strings (same rules as `finish-progress/v1`); hostname/PIDs/
pgids are local-machine advisory data inside gitignored `.project-loop/`.
Markers are ≤ 4 KiB (schema-bounded). Future export surfaces must exclude
`.project-loop/finish-attempts/` by default (constraint noted in the schema
header). Size bound justification: one live-class marker per running finish,
residue bounded by the table above plus operator cleanup.

## 10. Why process loss cannot fabricate success

1. Placement: marker code runs only before check execution or after outcome
   commits; unlink only at U1/U2 (§7.4–7.5), fault-injection-tested.
2. Non-participation: no completion-decision module imports lease state
   (import-boundary test); seeding forged/live/corrupt markers around a real
   run changes nothing in its result.
3. Authority: outcomes/transitions remain inside the existing validated
   transactions with freshness re-checks; v1 adds **zero** DB writes.
4. Degradation direction: every failure mode (unreadable marker, probe
   errors, create failure) reduces information or blocks a conclusion —
   `stale_interrupted` requires positive proof that nothing is running.

## 11. Deferred (each needs its own accepted design/gate)

Per-target atomic claim/election (requires more than per-token O_EXCL);
marker-failure abort policy (only sensible together with enforcement);
discard/cancel mutation with audit event; audit anomalies; authoritative
token anchors enabling per-token attribution; `pcl next` hints; MCP tool;
consolidating the two finish commit transactions.

Rejected alternatives: normalized `finish_attempts` table + migration
(ADR-004); SQLite start-event tracking (dead writers leave forever-open
state); whole-run flock (contradicts per-transaction lock doctrine; crash
hides intent); mid-flight check resumption (ephemeral clone makes it
dishonest); automatic retry/reap (issue non-goal); tokens inside packets
(forces v2); scan-then-refuse leasing (TOCTOU-unsound election).

Residual risks: wall-clock dependence (mitigated by R3/R5 and
fail-closed rows); pgid reuse within a boot (bounded by last-heartbeat
recency; noted in guidance); platform-absent start identity forces R10
conservatism; B1-class power-loss between create and fsync loses one run’s
visibility (correctness unaffected).

## 12. Test strategy

### 12.1 Failure injection (extends `tests/test_crash_concurrency.py`)

Existing machinery (`PCL_ENABLE_TEST_FAULTS=1` + exact
`PCL_TEST_FAULT_POINT`, abrupt `os._exit(137)`, timing-independent).

| Fault point | Asserts after abrupt exit / injection |
|---|---|
| FP-1 `finish_lease_marker_create_failure` (injected OSError) | run completes; result unchanged; no marker |
| FP-2 `finish_lease_after_marker_create` | residue present; classifies per §5 |
| FP-3 `finish_lease_mid_heartbeat_replace` | old/new bytes only, both schema-valid |
| FP-4 `finish_lease_after_check_evidence_commit` | dangling rows listed target-wide; marker preserved |
| FP-5 `finish_lease_after_outcome_commit_before_unlink` | outcome + marker coexist; no per-token attribution in payload |
| FP-6 `finish_lease_post_start_unexpected_exception` | marker preserved (NF-5) |

Concurrency: barrier-synchronized same-target starts ⇒ both succeed, two
distinct markers, both listed; different-target pairs independent;
commit-time correctness identical to single-writer baseline. No sleeps.

### 12.2 Gates per task

Standard gate per repo convention (`PYTHONPATH=src pytest`, `ruff check .`,
`validate --strict --json`, `render --json`) plus: no-progress finish
baseline byte-shape unchanged; `tests/test_finish.py` and
`tests/test_crash_concurrency.py` green; §6.3 corpus identical across
source/wheel/sdist.
