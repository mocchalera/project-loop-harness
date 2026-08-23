# Design: Durable and Resumable Finish Attempts After Process Loss

Status: **Proposed — design-gate candidate for Issue #3.** Implementation must
not start before the ADR and this design are accepted by the human gate
(`agent-tasks/0227-durable-finish-attempt-recovery.md`).

Date: 2026-08-23

Base: `origin/main` @ `da59b068f27becdc6a8bc857709f899787326638`

Origin: GitHub Issue #3 “[P1] Design durable and resumable finish attempts
after process loss”, residual risks in
[`docs/plan-p1-finish-progress-compact-output.md`](plan-p1-finish-progress-compact-output.md)
§10.

Companion decision: [`docs/adr/ADR-004-finish-attempt-recovery-store-decision.md`](adr/ADR-004-finish-attempt-recovery-store-decision.md)
(no normalized attempt store, no migration, no `completion-packet/v2`).

## 1. Problem, verified against origin/main

An actual `pcl finish --emit-packet` run can last from seconds to more than
twenty minutes (per-check timeout ceiling 1200 s,
`finish_recovery.FINISH_TIMEOUT_RECOVERY_STEPS_SECONDS`). During that window,
verified against `src/pcl/finish_execution.py@da59b06`:

1. **No durable record of the running attempt exists.** All durable writes
   happen after the check loop completes: check Evidence commits in its own
   transaction (`_commit_check_evidence_and_runner_authority`), then the
   completion packet or incomplete-attempt artifact commits in a second
   transaction (`_commit_completion_packet` / `_commit_finish_attempt`).
2. The `--progress` stream is ephemeral stderr presentation. A heartbeat
   proves only that the parent was waiting at emit time; it survives neither
   the process nor the terminal.
3. If the parent dies mid-run, the operator cannot distinguish:
   - “finish never ran”,
   - “finish ran and died before any commit” (nothing to show),
   - “finish committed everything but the parent died before printing”
     (durable state already advanced),
   - “finish committed check Evidence but died before the outcome commit”
     (partial durable state).
4. A killed run also leaves untracked residue: `.project-loop/tmp/finish-checks-*`
   stage directories and the isolated verification workspace clone
   (`finish_workspace.py` creates it with bare `tempfile.mkdtemp`, i.e. in
   the system temp directory, outside the project).

The post-commit case (3c) is already recoverable today through existing
surfaces (`pcl next --target <ID>`, `pcl evidence show`, idempotent packet
matching). The gap is pre-commit visibility, liveness classification, and safe
recovery guidance.

### 1.1 Invariants that must not change

- Completion semantics stay exactly as implemented: outcomes are produced only
  inside verified `BEGIN IMMEDIATE` transactions with target freshness
  re-checks (`FinishTargetReadinessChangedError`, terminal-readiness anchors).
- No false terminal outcome: nothing in this design participates in any
  completion decision path.
- Default (no-flag) finish JSON shape, exit codes, and command semantics are
  unchanged. One new typed refusal exit is added for same-target concurrent
  starts (§7.4); it fires only in a state that was previously undetectable.
- No daemon, hosted coordinator, cloud state, telemetry, or automatic retry.
- No `completion-packet/v2`; packet and attempt contracts are unchanged.

## 2. Attempt identity and the two-layer model

The design separates **authority** from **advisory liveness**:

| Layer | Artifact | Authority | Lifetime |
|---|---|---|---|
| Committed attempt record | `completion-packet/v1` or `finish-attempt/v1` content-addressed Evidence + `evidence` row + `evidence_links` + event (`completion_packet_created` / `finish_attempt_recorded`) | Authoritative proof of what happened | Project lifetime; never deleted |
| Attempt lease marker | `finish-lease-marker/v1` JSON file under `.project-loop/finish-attempts/` | Advisory only: proves someone *started*; never proves anything finished | Created at start, removed on every orderly exit; residue classified by inspection |

**Authoritative attempt identity** remains the existing content-derived ID:
`cp-sha256:<hash>` for packets, `fa-sha256:<hash>` for incomplete attempts
(`_finish_attempt_id`). This design does not mint a competing identity.

**In-flight attempt identity** is a fresh lease token `FL-<16 hex>` generated
per run. It is intentionally *not* embedded into packets (that would be a v1
contract change). Correlation between a lease marker and its eventual
committed record is computed at read time (§6.4), never stored as authority.

**State machine.** There is deliberately no persisted attempt state machine.
Persisted states would require compensating mutations to retire (who writes
“abandoned” when the writer is dead?) and create a second source of truth.
Instead:

```text
(run starts)
    │ create lease marker (O_EXCL, fsync)
    ▼
RUNNING ──heartbeat──► RUNNING                (marker rewritten atomically)
    │
    ├─ orderly end (success, INCOMPLETE_*, typed error, exception):
    │     existing outcome commits run first, THEN marker unlink
    ▼
TERMINAL (existing packet/attempt artifacts are the only durable trace)

(process loss at any point)
    ▼
RESIDUE MARKER → classified read-only at inspect time:
    running_live | indeterminate | interrupted_lost |
    interrupted_partial_evidence | completed_committed |
    discarded_residue | unreadable
```

Classification (§5) is derived, deterministic per (marker bytes, filesystem,
DB snapshot, host observations), and never mutates state. The authoritative
outcome vocabulary is unchanged: the six packet outcomes plus
`INCOMPLETE_VALIDATION` attempts. A lost attempt has **no** outcome; it is
never promoted to success nor recorded as failure.

## 3. Failure matrix

| # | Disruptor | What happens today (@da59b06) | With this design | Classification at inspect |
|---|---|---|---|---|
| F1 | Terminal disconnect (SIGHUP to parent, closed pipe) | Progress stream truncates; if parent handles HUP and exits, identical to F2 | Marker residue remains unless parent reached orderly exit | `running_live` until heartbeat TTL, then `interrupted_lost`/`interrupted_partial_evidence` |
| F2 | Parent crash / `kill -9` / OOM | Nothing durable (pre-commit); dangling check Evidence possible if killed between the two commits | Same durability, but visible: marker with frozen `heartbeat_at` | Per §5 ladder; heartbeat age + PID/boot signals decide |
| F3 | Host restart / power loss | Same as F2; additionally unflushed marker may vanish (acceptable: degrades to status quo visibility) | `boot_id` mismatch classifies all markers stale immediately, regardless of mtime | `interrupted_*` |
| F4 | Child check exits nonzero / spawn error / child crash | Guarded executor records failed result; run continues to outcome commit; INCOMPLETE packet retained, exit 1 | Unchanged; marker removed at orderly exit | Historical packet lookup; no residue |
| F5 | Child check timeout | `timed_out` status → `timeout_recovery` steps (600→1200 s) → INCOMPLETE_VALIDATION packet with `next_action`; committed durably | Unchanged; marker removed at orderly exit | Existing `pcl next` recovery route; no residue |
| F6 | Whole-run external timeout (supervisor kills parent) | Identical to F2 | Identical to F2 | Per §5 ladder |
| F7 | Stale attempt (any F1/F2/F3/F6 residue later found) | Undetectable today | Explicit classification + guidance; same-target re-start refused while live-looking | §5 states |
| F8 | Target readiness drift between commits (non-crash) | Check-Evidence transaction already committed; outcome transaction rolls back (`FinishTargetReadinessChangedError`); dangling check Evidence **already occurs today, invisibly** | Same rollback; inspect surfaces dangling rows target-scoped, independent of any marker | `uncommitted_check_evidence` listing (§5, trailing rule) |
| F9 | Concurrent finish, same target | Both runs execute checks wastefully; correctness preserved by commit-time freshness checks; confusing duplicate artifacts | Second start refuses with typed `finish_attempt_lease_live` while first looks alive (§7.4) | n/a (refusal prevents residue ambiguity) |
| F10 | Concurrent finish, different targets | Works today | Unchanged; leases are per-target | n/a |
| F11 | Disk full / EACCES on marker write | n/a | Fail-closed **before** check execution: typed error, exit 2, zero state mutated (§7.3) | none (run never started) |

F8 deserves emphasis: partial check-Evidence state is a *normal-path*
exposure today, not only a crash exposure. Surfacing it is part of this
design even though fixing the two-transaction split is out of scope
(consolidating it would change commit ordering and needs its own review).

## 4. Lease marker contract (`finish-lease-marker/v1`)

Location: `.project-loop/finish-attempts/<target_type>-<target_id>-<token>.json`
(gitignored like all of `.project-loop`; outside `evidence/` so audit orphan
scans are unaffected; a dedicated audit anomaly is specified in §9.3).

Canonical JSON, UTF-8, sorted keys, compact separators, trailing newline —
same serialization rules as other PLH artifacts. Schema:
`pcl/contracts/schemas/finish-lease-marker-v1.schema.json`,
`additionalProperties: false`.

```json
{
  "contract_version": "finish-lease-marker/v1",
  "token": "FL-0f1e2d3c4b5a6978",
  "target": {"type": "task", "id": "T-0151"},
  "target_source": "explicit",
  "pid": 4711,
  "boot_id": "8c8f2f30-…",
  "hostname": "worker.local",
  "started_at": "2026-08-23T09:00:00Z",
  "heartbeat_at": "2026-08-23T09:04:30Z",
  "heartbeat_count": 9,
  "phase": "checks",
  "check_index": 2,
  "check_count": 3,
  "check_config_keys": ["lint", "typecheck", "test"],
  "timeout_seconds": 600,
  "plan_identity": {
    "base_revision": "<sha>",
    "head_revision": "<sha>",
    "diff_sha256": "sha256:<64hex>",
    "input_manifest_sha256": "sha256:<64hex>"
  },
  "pcl_version": "0.6.x"
}
```

Field rules:

- `token`: `FL-` + 16 lowercase hex (UUID4-derived). Collision retry once;
  second collision is a typed error (astronomically unlikely, fail-closed).
- `phase` / `check_index` / `check_count` mirror the allowed progress events’
  phase vocabulary (`planning`, `workspace_preparation`, `checks`,
  `repository_snapshot`, `strict_validation`, `evidence_commit`).
- `plan_identity` copies the *planned* repository snapshot and input-manifest
  digest captured during planning. These are correlation keys only (§6.4).
- Sanitization inherits the `finish-progress/v1` rules verbatim: no raw argv,
  no environment values, no captured output, no secret-shaped strings. Only
  public configuration key names appear.
- Unknown `contract_version` or schema-invalid content ⇒ classified
  `unreadable` at inspect; never guessed, never deleted automatically.

Constants (module-level, not CLI flags in v1, mirroring the heartbeat
decision in the P1 plan): `FINISH_LEASE_HEARTBEAT_SECONDS = 30`,
`FINISH_LEASE_STALE_AFTER_SECONDS = 120`.

## 5. Liveness classification

Computed read-only at inspect time. Signals, in precedence order:

1. **Boot identity**: Linux `/proc/sys/kernel/random/boot_id`; macOS
   `sysctl -n kern.boottime`. Unreadable ⇒ `boot_id: null`; null never claims
   same-boot certainty (falls through to signals 2–3). Mismatched boot id
   ⇒ stale immediately (handles clock jumps across restarts).
2. **Heartbeat freshness**: `now − heartbeat_at ≤ FINISH_LEASE_STALE_AFTER_SECONDS`
   ⇒ live-looking, regardless of PID probes. Rationale: heartbeats stop when
   the writer dies; a fresh heartbeat implies a live writer within TTL. This
   makes the soft lease (§7.4) conservative in the safe direction.
3. **PID aliveness**: `os.kill(pid, 0)`; `ProcessLookupError` ⇒ dead,
   `PermissionError` ⇒ treat as alive (EPERM means the process exists).

| Condition (marker present; rows 1–3 additionally assume no correlated committed record) | State | Meaning |
|---|---|---|
| heartbeat fresh | `running_live` | A finish for this target is (very likely) executing now. |
| heartbeat stale AND pid alive AND boot matches | `indeterminate` | Owner exists but stopped beating (SIGSTOP, hung I/O). Never auto-assumed dead. |
| heartbeat stale AND (pid dead OR boot mismatch) | `interrupted_lost` | Process gone without committing an outcome. Safe to retry from scratch. |
| marker + committed record correlated (§6.4) | `completed_committed` | Outcome actually landed; report artifact IDs; marker is removable residue. |
| marker + discard event for token | `discarded_residue` | Event committed but unlink crashed; repeat discard is a no-op cleanup. |
| schema-invalid / unknown version | `unreadable` | Human review; never parsed further. |

Additionally, independent of markers, inspect reports dangling check Evidence
(`uncommitted_check_evidence`): target-linked `verification_check` Evidence
rows created after the target’s last `completion_packet_created` /
`finish_attempt_recorded` event (bounded `LIMIT 100`, newest first). This
covers F2-between-commits and F8.

Every state maps to explicit guidance records (`code`, `message`,
`command?`) — see §6.2. Guidance commands are display-only strings; nothing
auto-executes them (repository doctrine: suggested_commands are never run).

## 6. Frozen public CLI/JSON contracts

New top-level noun group, following the `audit`/`jobs` sub-noun pattern
(`parser_control.py`), leaving the flag-heavy `finish` parser untouched:

```text
pcl attempts inspect [--target T-XXXX|G-XXXX] [--json]
pcl attempts discard FL-xxxxxxxxxxxxxxxx --reason "<text>" [--json]
```

### 6.1 Scope rules

- Requires an initialized project; otherwise usage error, exit 2.
- `inspect` is strictly read-only (read-only DB connection; no lock upgrades;
  no marker writes; no event appends; does not flush the projector).
- `discard` is the only mutating surface in this design besides the implicit
  marker lifecycle inside `finish`.
- `--dry-run` finishes and planner-mode `pcl finish` never create markers.
- MCP exposure is explicitly out of scope for the first slice; the JSON
  contract is designed so a later MCP tool is additive.

### 6.2 `attempts inspect` → `finish-attempt-inspect/v1`

Exit codes: `0` always when the command ran (findings live in the payload);
`2` usage/uninitialized project.

```json
{
  "ok": true,
  "contract_version": "finish-attempt-inspect/v1",
  "generated_at": "2026-08-23T09:30:00Z",
  "filter": {"target": {"type": "task", "id": "T-0151"}},
  "counts": {
    "total": 2,
    "running_live": 1,
    "indeterminate": 0,
    "interrupted_lost": 1,
    "interrupted_partial_evidence": 0,
    "completed_committed": 0,
    "discarded_residue": 0,
    "unreadable": 0
  },
  "attempts": [
    {
      "token": "FL-0f1e2d3c4b5a6978",
      "marker_path": ".project-loop/finish-attempts/task-T-0151-FL-0f1e2d3c4b5a6978.json",
      "state": "running_live",
      "target": {"type": "task", "id": "T-0151"},
      "started_at": "2026-08-23T09:00:00Z",
      "last_heartbeat_at": "2026-08-23T09:29:41Z",
      "heartbeat_age_seconds": 19.2,
      "liveness": {
        "boot_id_match": true,
        "pid_alive": true,
        "heartbeat_fresh": true
      },
      "correlation": null,
      "guidance": [
        {
          "code": "finish_attempt_lease_live",
          "message": "A finish attempt for task T-0151 appears active. Do not start another finish for this target; wait or investigate the owning process.",
          "command": null
        }
      ]
    },
    {
      "token": "FL-77ab01fe44cc9012",
      "state": "interrupted_lost",
      "started_at": "2026-08-22T18:02:11Z",
      "last_heartbeat_at": "2026-08-22T18:05:31Z",
      "liveness": {"boot_id_match": false, "pid_alive": false, "heartbeat_fresh": false},
      "correlation": null,
      "guidance": [
        {
          "code": "finish_attempt_interrupted_retry_safe",
          "message": "This attempt was interrupted before any completion record. Re-running finish is safe and fail-closed; no incomplete attempt becomes a success.",
          "command": "pcl finish --emit-packet --task T-0151 --json"
        },
        {
          "code": "finish_attempt_discard_available",
          "message": "Retire this marker after deciding.",
          "command": "pcl attempts discard FL-77ab01fe44cc9012 --reason \"<reason>\""
        }
      ]
    }
  ],
  "uncommitted_check_evidence": [],
  "truncated": false
}
```

Contract details:

- Listing bounded to the 100 newest markers by `started_at`, `truncated: true`
  beyond that. Filtering by `--target` echoes the filter; unknown target IDs
  return an empty list (predictable), not an error.
- `interrupted_partial_evidence` attempts carry `check_evidence_ids` and
  `strict_validation` context copied from the marker-era rows where resolvable.
- Correlation block (when `completed_committed`): `{packet_id?, attempt_id?,
  evidence_ids, confidence: "identity"|"temporal"|"ambiguous"}`.
- `unreadable` entries include the parse/schema error class, never raw file
  contents.

### 6.3 `attempts discard`

One `BEGIN IMMEDIATE` transaction via the service layer + transactional
outbox (ADR-002 contract):

1. Read and classify the marker. Refuse (exit 1, typed
   `finish_attempt_lease_live`) when classified `running_live`. Refuse
   `indeterminate` too (exit 1, `finish_attempt_indeterminate`) — a stopped
   process may resume; the human resolves the owner first.
2. Append event `finish_attempt_discarded`, entity-bound to the marker’s
   target, payload:
   `{contract_version, token, target, reason (bounded 500 chars, redacted),
   classification_inputs: {observed_at, heartbeat_at, pid_alive, boot_id_match}}`.
3. Commit. Then unlink the marker (best-effort fsync of directory).
4. Crash windows are ordered event-first: marker+event residue classifies as
   `discarded_residue`; repeating the command is an idempotent no-op
   (`changed: false`) that cleans the residue without appending a duplicate
   event (dedup by prior event scan for the token, target-bounded).

Bulk form: `pcl attempts discard --stale --reason "<text>" [--json]`
retires every marker classified `interrupted_lost` / `interrupted_partial_evidence`
/ `discarded_residue` (never live/indeterminate/unreadable), one event per
token, reporting per-token results. Exit `0` when at least the requested
retirements succeeded or there was nothing to do; `1` if any token was
refused; `2` usage.

Result envelope (single discard):

```json
{
  "ok": true,
  "contract_version": "finish-attempt-discard/v1",
  "token": "FL-77ab01fe44cc9012",
  "changed": true,
  "event_id": "EV-…",
  "residue_cleaned": true
}
```

### 6.4 Correlation rules (read-time, deterministic)

Given marker `M` for target `T`:

1. **Identity match** (confidence `identity`): a committed packet/attempt for
   `T` whose stored repository block equals `M.plan_identity` on
   `(base_revision, head_revision, diff_sha256)` — or whose
   `input_manifest_sha256` equals the marker’s — created at or after
   `M.started_at − 300 s`.
2. **Temporal ownership fallback** (confidence `temporal`): any committed
   packet/attempt for `T` created after `M.started_at` and before the next
   marker start for `T`. This covers `race_detected` runs whose final
   snapshot legitimately differs from the plan identity.
3. Multiple candidates ⇒ `ambiguous`: list all; never auto-select; guidance
   routes to `pcl evidence show` for each.

Correlation influences only advisory classification and guidance. It can
never alter outcomes, transitions, or validation.

### 6.5 Positive/negative fixtures (frozen)

Positive fixtures (seeded projects, exact-JSON assertions):

| Fixture | Setup | Expected |
|---|---|---|
| PF-1 | Live marker (heartbeat now, own PID) + no record | state `running_live`; refusal fixture companion |
| PF-2 | Stale marker (old heartbeat, foreign PID, current boot) | `interrupted_lost`; retry-safe + discard guidance |
| PF-3 | Stale marker + committed packet correlated by identity | `completed_committed` with `packet_id`/`evidence_id`, confidence `identity` |
| PF-4 | Stale marker + race-detected packet (snapshot differs) | `completed_committed`, confidence `temporal` |
| PF-5 | Stale marker + dangling check Evidence rows, no outcome | `interrupted_partial_evidence` + `uncommitted_check_evidence` listing |
| PF-6 | Discard event + leftover marker | `discarded_residue`; repeat discard no-op `changed:false` |
| PF-7 | Two markers same target (one live one stale) | Both listed independently; counts correct |
| PF-8 | Empty project section | Empty lists, zero counts, exit 0 |

Negative fixtures:

| Fixture | Setup | Expected |
|---|---|---|
| NF-1 | Corrupt JSON marker | `unreadable`; exit still 0 on inspect; never crashes |
| NF-2 | Unknown `contract_version` marker | `unreadable` with version class reported |
| NF-3 | `discard` on live token | exit 1, typed `finish_attempt_lease_live`, no mutation |
| NF-4 | `discard` on indeterminate token | exit 1, typed `finish_attempt_indeterminate`, no mutation |
| NF-5 | `discard` unknown token | exit 2 usage-class error |
| NF-6 | Start finish while PF-1 marker present | exit 2, typed `finish_attempt_lease_live`, zero state mutated |
| NF-7 | `inspect` on uninitialized project | exit 2 usage error |
| NF-8 | Oversized/malformed `--reason` (>500 chars or control chars) | exit 2, rejected before any mutation |
| NF-9 | Marker write fails (injected ENOSPC/EACCES) during start | exit 2 typed `finish_lease_unavailable`, no checks executed |

All fixtures use injected clocks/filesystems; no real sleeps; deterministic on
Linux and macOS.

## 7. Lifecycle integration and crash-safe ordering

### 7.1 Where marker creation happens

In `emit_finish_packet`, strictly **after**: argument/config validation,
planning, the idempotent-existing-completed-packet short circuit, and the
blocked-check rejection — and strictly **before**: stage-directory creation,
isolated workspace preparation, and any check execution. A marker therefore
never exists for runs that end in pure usage/configuration errors, and never
coexists with a short-circuit idempotent return.

### 7.2 Ordered boundary table

| Boundary | Operation | Crash here ⇒ | Idempotency / convergence |
|---|---|---|---|
| B0 | Before marker create (validation failures) | nothing (today’s behavior) | safe command retry |
| B0′ | Marker create fails (ENOSPC/EACCES/O_EXCL loss) | typed abort before checks; zero state mutated | safe retry after disk resolution |
| B1 | After create, before fsync | marker may be absent after power loss | equivalent to “never started”; visibility degrades to status quo; acceptable because the layer is advisory |
| B2 | During heartbeat rewrite (tmp + `os.replace`) | old or new marker bytes, never torn | staleness misclassification only ever in the *conservative* direction (may refuse a start that would have been fine; never allows an unsafe start) |
| B3 | After check-Evidence commit, before outcome commit | dangling check Evidence + marker | pre-existing exposure (also reachable via F8); surfaced by inspect; retry converges: rerun creates new check Evidence rows and proceeds; historical rows remain as honest history |
| B4 | After packet/attempt commit, before marker unlink | marker + committed record | classified `completed_committed`; rerun hits the existing idempotent packet path (`idempotent: true, changed: false`) and removes the marker in its finally block |
| B5 | During unlink | dir entry present or absent | both classify correctly |
| B6 | Discard: event committed, before unlink | marker + event | `discarded_residue`; repeat discard cleans up, no duplicate event |

Ordering rule (normative): **outcome commits precede marker removal**; marker
creation precedes check execution. Removing the marker before the outcome
commit would open a window where a crash leaves neither marker nor record —
the invisible state this design exists to close.

### 7.3 Fail-closed marker failures

If the marker cannot be created (B0′), finish aborts with typed error
`finish_lease_unavailable`, exit 2, before any execution or mutation.
Rationale: the feature promises observable attempts; silently degrading to an
invisible ten-minute run reproduces the original problem. Runtime heartbeat
write failures after the run started are *degraded, not fatal* (caught,
counted internally, never affect verification/persistence — same doctrine as
progress delivery), because aborting a half-executed run cannot undo checks
and would only manufacture a new failure mode. Heartbeat degradation shows up
later as heartbeat gaps in classification; residual risk documented in §11.

### 7.4 Soft lease enforcement

Before creating a marker, finish scans `.project-loop/finish-attempts/` for a
live-looking marker (`running_live`) bound to the same target. Found ⇒ typed
error `finish_attempt_lease_live`, exit 2, guidance pointing at
`pcl attempts inspect --target …`. `indeterminate` also refuses (safe
direction). No override flag in v1: a fresh heartbeat requires a live writer,
so refusal is correct; an `indeterminate` owner is resolvable by the operator
(`kill`/`fg`) far more safely than by an override switch. Different targets
are never blocked. The lease is advisory: it guards *starting*, holds no lock
file, expires purely by TTL, and cannot deadlock.

Observable-behavior note: two same-target finishes used to race wastefully;
they now serialize by refusal. This is an intended semantic, called out in the
compatibility notes rather than hidden behind a flag.

### 7.5 Heartbeat mechanics

A finish-local ticker thread mirrors the proven `FinishProgressReporter`
mechanics: injectable clock/sink, bounded join (≤2 s) at every exit path,
exceptions swallowed-and-counted, no subprocess ownership. It updates the
marker at every check boundary, phase transition, and on the 30 s cadence
during long checks — including when `--progress` was not requested (the lease
is default-on; progress remains opt-in). The default-shape stdout result gains
**no** new fields from leasing.

## 8. Relationship to existing proof surfaces

- **Check Evidence** (`completion_check` type, `verification_check` links):
  unchanged producer; becomes *visible* in partial states via inspect.
- **Repository snapshots / idempotency**: markers live under `.project-loop/`
  and are therefore excluded from `diff_sha256` bytes and from the `dirty`
  flag (both computed excluding `.project-loop/**`,
  `finish_repository.py@da59b06`). They appear only in the result JSON’s
  `harness_local_state` presentation listing while a run is in flight, never
  inside packet content, so `_matching_completion_packet` idempotency and all
  race guards are unaffected.
- **Incomplete-attempt Evidence** (`finish-attempt/v1` +
  `finish_attempt_recorded`): unchanged; remains the authoritative record for
  workspace-input-mutation incompletes. Lost attempts produce *none* — and
  must not: fabricating an attempt artifact post-mortem would forge proof.
- **Completion packets** (`completion-packet/v1`): unchanged; still the only
  route to `COMPLETED_*` and target transitions. Markers never referenced
  from packets (no v1 field changes).
- **Target binding**: marker binding mirrors `--task/--goal/--run` resolution
  output (`target_source: explicit|planner`) exactly like progress bindings;
  inspect filtering uses the same routing-target resolver vocabulary.
- **Terminal readiness**: untouched. Freshness re-checks continue to gate
  every transition; this design adds no bypass and reads receipts only.
- **`pcl next` routing**: unchanged in the required slice; optional bounded
  enhancement (hint when live markers exist for the routed target) is listed
  as cut-line task T-H2.
- **Recovery playbook**: gains a routing row mapping
  `finish_attempt_*`/`stale_finish_attempt_marker` findings to
  `pcl attempts inspect` (documentation-only change, shipped with T-H).

## 9. Retention, privacy, and redaction

- **Size bound**: one marker ≤ 4 KiB; at most one live marker per target
  (soft lease); total residue bounded only by interrupted-run count. Bulk
  `discard --stale` and the audit anomaly keep residue operator-visible and
  cheap; hundreds of 4 KiB files are negligible. No automatic time-based
  deletion (repository doctrine: no silent deletes); retention is enforced
  through explicit retirement, not garbage collection.
- **Content bounds**: enumerated fields only (schema
  `additionalProperties: false`); no argv, env, output, secrets; hostname/PID
  are local-machine advisory data inside gitignored `.project-loop/`.
- **Redaction**: `--reason` passes the shared redaction pass and length cap
  before entering events. Future export surfaces (e.g., evidence export
  bundles) must exclude `.project-loop/finish-attempts/` by default — noted
  in the schema doc header so the constraint ships with the contract.
- **Events**: `finish_attempt_discarded` payloads carry classification inputs
  and redacted reasons only; they never embed marker file bodies.

## 10. Proof: process loss cannot create a false `COMPLETED_*` or mutate targets

By construction, with enforceable test assertions:

1. **T1 — placement**: marker code executes only (a) before check execution
   or (b) after outcome commits. Fault-injection tests assert durable state at
   every boundary B0–B6 (§12).
2. **T2 — non-participation**: no completion-decision code imports or reads
   lease state. Enforced by a unit test asserting that
   `_completion_outcome`/`_apply_terminal_transition`/
   `evaluate_terminal_readiness` modules do not import the lease module, plus
   a behavior test: seeding forged/corrupt/live markers around a finish run
   changes nothing in its result except the two defined refusals (which fire
   before execution and cannot fake success).
3. **T3 — authority unchanged**: outcomes/transitions still occur exclusively
   inside the existing validated `BEGIN IMMEDIATE` commits with freshness
   re-checks; the diff introduces no new write to tasks/goals/events other
   than the additive `finish_attempt_discarded` event.
4. **T4 — refusal direction**: every ambiguous or degraded condition
   (indeterminate liveness, unreadable marker, marker-write failure) blocks
   *starting* work; none permits skipping verification or recording an
   outcome. Therefore the design can only reduce false-progress risk, never
   add it.

## 11. Residual risks (accepted for v1)

- Heartbeat degradation after B0′-adjacent I/O trouble can make a genuinely
  live run look stale to *classification*; the soft lease errs toward
  refusing starts, and the operator resolves via inspect + process tools.
- Wall-clock dependence: NTP steps could momentarily distort heartbeat age;
  boot-id mismatch dominates across restarts, PID probe dominates within a
  boot; worst case is a wrong conservative label requiring human confirmation.
- Between-commits dangling check Evidence (F8/F-B3) remains structurally
  possible; this design makes it visible but does not consolidate the two
  transactions (deliberate scope boundary; changing commit ordering deserves
  its own reviewed slice).
- Marker lost to power failure between create and fsync (B1) degrades that
  one run’s recoverability to status-quo invisibility. Correctness unaffected.
- `os.kill(pid, 0)` cannot identify *which* process behind a reused PID beat
  the heartbeat; mitigated by TTL-first logic and the indeterminate state.

## 12. Test strategy

### 12.1 Failure injection (extends `tests/test_crash_concurrency.py`)

Uses the existing machinery (`PCL_ENABLE_TEST_FAULTS=1` +
exact `PCL_TEST_FAULT_POINT`, abrupt `os._exit(137)`, timing-independent
assertions). New fault points (names frozen here):

| Fault point | Asserts after abrupt exit |
|---|---|
| `finish_lease_before_marker_write` | no marker; no check ran; DB unchanged; exit path clean |
| `finish_lease_after_marker_create` | marker present; inspect classifies stale after simulated death; retry safe |
| `finish_lease_mid_heartbeat_replace` | marker is old-bytes or new-bytes, both valid per schema; classification deterministic |
| `finish_lease_after_check_evidence_commit` | dangling check Evidence listed by inspect; marker present; no packet |
| `finish_lease_after_packet_commit_before_unlink` | packet + marker coexist; `completed_committed`; repeat finish is idempotent and cleans residue |
| `finish_attempt_discard_after_event_commit` | event present; marker residue; repeat discard idempotent |

Concurrency cases (barrier-synchronized, no sleeps): N processes start
same-target finish concurrently ⇒ exactly one O_EXCL winner, others exit 2
typed refusal; different-target pairs proceed; winner’s eventual commit
unchanged versus single-writer baseline.

### 12.2 Contract fixtures

- New schemas ship under `src/pcl/contracts/schemas/` (covered by the
  existing `contracts/schemas/*.json` package-data glob in `pyproject.toml`)
  and are exercised by the existing packaged-contract test pattern
  (importlib.resources for wheel presence; sdist file-list assertion), same
  as `completion-packet-v1.schema.json`.
- Source fixtures: seeded projects under `tests/fixtures/` covering PF-1…PF-8,
  NF-1…NF-9, validated through the CLI with `--json` and byte-compared.
- Python contract validators for the marker and inspect envelope follow the
  existing `pcl.contracts.*` module style (fail-closed, path-addressed
  errors, NaN/Infinity rejection).

### 12.3 Behavior gates per implementation task

Each task runs the standard gate (`PYTHONPATH=src pytest`, `ruff check .`,
`validate --strict --json`, `render --json`) and must keep green: the
existing no-progress finish regression set (TC-0184 baseline shape),
`tests/test_finish.py`, `tests/test_crash_concurrency.py`, and the strict
validator (new event type accepted additively).

## 13. Explicitly rejected alternatives

- **Normalized `finish_attempts` table + migration** — approval-gated,
  premature (see ADR-004); buys queryability the local single-writer CLI does
  not need; creates orphan-row lifecycle problems mirroring the ones it
  solves.
- **Start-event in SQLite as the sole tracker** — a permanent `started` row
  with no writer left to close it forces either forever-open states or
  compensating events written by strangers (inspect would need write paths),
  i.e., a second state machine to operate.
- **Long-held flock lease for the whole run** — contradicts the
  per-transaction lock doctrine (`locks.py`, ADR-002 §4.3); a crashed holder
  releases the OS lock but leaves intent invisible, combining the weaknesses
  of both worlds.
- **Mid-flight check resumption (“true resume”)** — impossible honestly:
  checks run in an ephemeral isolated clone that dies with the process;
  pretending to resume would fabricate continuity that no Evidence supports.
  The design instead makes *retry-with-inspection* provably safe.
- **Automatic retry/reap of stale attempts** — banned by issue non-goals;
  retirement stays human-triggered via `discard`.
- **Embedding lease tokens into packets** — requires `completion-packet/v2`;
  read-time correlation achieves the same operational value without touching
  a frozen contract.
