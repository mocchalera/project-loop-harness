# P1 Plan: finish progress visibility and compact actual output

Status: planned, implementation not authorized  
Date: 2026-07-28  
PCL target: `G-0073` / `T-0151` / `F-0080`  
Stories: `US-0082`, `US-0083`  
Tests: `TC-0184`–`TC-0192`

## 1. Decision and scope

The selected P1 entry slice is limited to two frictions observed during the
P0-6 / P0-7 dogfood:

1. an actual `pcl finish --emit-packet` can run for about ten minutes without
   showing its current phase, check, or elapsed progress;
2. the actual finish result cannot use the existing dry-run projection flags
   and produced a single JSON line of more than about 48k tokens.

This plan does not authorize implementation. Implementation starts only after
the human confirms this plan and the Story semantics.

The slice must not add:

- a database migration or new normalized attempt table;
- a runtime dependency;
- `completion-packet/v2`;
- a runner-specific structured reporter;
- durable or resumable live-progress storage;
- Cockpit or external-service auto-ingest;
- telemetry, publication, push, or PR work.

The existing completion packet, finish attempt, check Evidence, terminal
readiness, timeout recovery, target binding, and guarded-execution behavior
remain authoritative.

## 2. Success criteria

### 2.1 Live progress

An explicitly requested actual finish emits bounded, target-bound progress to
stderr while stdout remains exactly one final JSON document.

The stream:

- identifies preparation, each check, bounded heartbeats during a long check,
  validation, commit, and the true terminal outcome;
- uses a stable `finish-progress/v1` envelope and monotonically increasing
  sequence numbers;
- does not expose raw argv, environment values, captured stdout/stderr, or
  secret-shaped command output;
- does not append PCL events, Evidence, progress receipts, or database rows;
- does not change the check result, packet/attempt, target transition, timeout
  recovery, or exit code if delivery fails;
- is opt-in, so all no-progress invocations retain existing behavior.

### 2.2 Compact actual result

The existing `--summary`, `--output-offset`, `--output-limit`, and
`--exclude-machine-state` flags become valid for an actual
`finish --emit-packet` result as presentation-only options.

The compact result retains:

- `target` and explicit `target_binding`;
- repository base/head, dirty state, and `diff_sha256`;
- `changed`, `idempotent`, `race_detected`, and `exit_code`;
- compact check outcomes, failure classification, Evidence IDs, and stability
  anchors;
- packet or incomplete-attempt ID, Evidence ID, path, and outcome;
- terminal-readiness status, reason counts/codes, and terminal permission;
- target transition and timeout recovery;
- complete total/eligible/returned/omitted counts and the repository snapshot
  digest.

It may omit or summarize only bulky presentation detail:

- repository `changes` and `harness_local_state` rows;
- full stdout/stderr metadata and permission/environment detail repeated under
  each check;
- full input-manifest entries and workspace effect-change rows;
- repeated strict-warning and terminal-readiness detail rows.

Projection happens only after the actual finish operation has produced its
normal in-memory result. The stored packet, attempt, Evidence artifacts, event
payloads, hashes, target transition, and command exit code are unchanged.

No projection flag means the existing public JSON shape remains unchanged.
The current dry-run projection shape also remains unchanged.

## 3. Story contracts

### US-0082 — target-bound live progress

As a coding agent or supervising operator, I want to observe the target,
current phase/check, elapsed heartbeat, and terminal outcome while an actual
finish runs, so that I can distinguish active work from a timeout or failure
without breaking the final machine-readable result.

Expected behavior:

- progress is explicitly enabled with `--progress text` or
  `--progress jsonl`;
- progress is written to stderr and the final result remains on stdout;
- the stream is ordered, target-bound, bounded, and sanitized;
- live progress is ephemeral presentation, not durable PCL state;
- omitted `--progress` preserves current behavior.

### US-0083 — compact actual result

As a coding agent or operator, I want a compact projection of an actual finish
result, so that I can retain proof anchors and recovery decisions without
consuming tens of thousands of tokens.

Expected behavior:

- the current projection flags work for both dry-run and actual packet modes;
- actual summary retains the proof and decision anchors listed in section 2.2;
- omission/filtering is reported with counts and never changes the authoritative
  snapshot or stored proof;
- invalid combinations fail before checks or state mutation;
- omitted projection flags preserve the current public JSON shape.

Both Stories remain `draft` until the human explicitly approves their semantic
contract.

## 4. Proposed CLI contract

```text
pcl finish --emit-packet --task T-XXXX \
  --progress jsonl \
  --summary \
  --exclude-machine-state \
  --json
```

### 4.1 Progress option

Add:

```text
--progress {text,jsonl}
```

Rules:

- it requires `--emit-packet`;
- it is valid only for actual execution, not `--dry-run`;
- omission means disabled;
- records go to stderr in both `--json` and human-output modes;
- stdout contains only the existing final human or JSON result;
- invalid values or mode combinations fail before planning or mutation.

The first slice does not make progress automatic. An automatic terminal default
can be considered later only after real-use evidence.

### 4.2 Progress envelope

JSONL uses one object per line:

```json
{
  "contract_version": "finish-progress/v1",
  "sequence": 3,
  "event": "check_heartbeat",
  "phase": "checks",
  "status": "running",
  "target_binding": {
    "target_type": "task",
    "target_id": "T-0151",
    "source": "explicit"
  },
  "check": {
    "index": 1,
    "count": 2,
    "config_key": "project.commands.test"
  },
  "elapsed_seconds": 60.0
}
```

Allowed events:

1. `finish_started`;
2. `phase_started` / `phase_finished`;
3. `check_started`;
4. `check_heartbeat`;
5. `check_finished`;
6. `finish_finished`.

Allowed phases:

- `planning`;
- `workspace_preparation`;
- `checks`;
- `repository_snapshot`;
- `strict_validation`;
- `evidence_commit`.

The terminal record reports the actual final status:

- `completed`;
- `incomplete`;
- `failed`;
- `timed_out`.

The envelope uses elapsed monotonic time and a monotonic sequence. It does not
promise byte-identical timestamps. Tests inject the clock and sink.

The check identity is limited to index/count and the public configuration key.
It excludes raw/resolved argv because configuration can accidentally contain
sensitive values. It also excludes captured output and environment values.

### 4.3 Heartbeat and delivery

The default heartbeat interval is 30 seconds and is not a new public tuning
surface in this slice.

A finish-local reporter wraps the existing synchronous
`execute_planned_guarded_command` call:

1. emit `check_started`;
2. start one bounded heartbeat worker;
3. call the unchanged guarded executor;
4. stop and join the worker;
5. emit `check_finished` from the returned result.

This avoids changing subprocess timeout and termination behavior in
`guarded_process.py`. The reporter owns no subprocess and never reads command
output.

The callback is optional. With no callback, `emit_finish_packet` follows the
current path. Reporter/sink exceptions are caught and counted; they cannot
change verification or persistence. When progress was requested, the final
presentation adds a compact `progress_delivery` summary with requested format,
emitted count, dropped count, and `complete` or `degraded` status.

This is not a durable receipt. If the parent process is killed, the stream can
end without a terminal record. Pollable/resumable attempts require a separate
design and, if normalized storage is needed, separate migration approval.

## 5. Compact result contract

### 5.1 Compatibility boundary

The implementation reuses the pure projection logic internally but preserves
the two existing public paths:

- dry-run projection remains `finish-output-projection/v1` with its current
  keys and behavior;
- actual projection uses the same `output_projection.contract_version` and
  adds executed-result section counts only when the source is an actual result.

No flag is changed, renamed, or made implicit. No projection is applied before
`emit_finish_packet` returns.

### 5.2 Actual summary check row

Each projected check contains only:

- `contract_version`;
- `evidence_id`;
- `status` and `exit_code`;
- `failure_phase` and `failure_kind`;
- runner and assertion status;
- output-truncated and redacted booleans;
- attempt identity and execution identity hashes;
- stability status, reproducibility, attempt count, and remaining attempts;
- reuse status/anchor when present.

Full command text, output paths/metadata, permission contract, environment
contract, toolchain detail, and full stability history remain available in the
write-once check Evidence.

### 5.3 Execution and validation summary

Actual summary keeps:

- isolated workspace kind and sharing booleans;
- materialization and effect classifications;
- input-manifest hashes and aggregate counts;
- strict validation `ok`, error/warning counts, and stable finding/reason codes;
- terminal-readiness contract/status/permission, reason counts/codes, and exact
  read-only recovery command when present.

Full rows remain available through the no-flag result and persisted Evidence.

### 5.4 Size and omission acceptance

For the deterministic scale fixture used by `TC-0189`, containing at least 500
change rows and 200 repeated warning/effect rows:

- actual `--summary --exclude-machine-state` is at most 16 KiB UTF-8;
- no unbounded row array remains;
- every omitted section reports total, eligible, returned, and omitted counts;
- the repository `diff_sha256` and packet/attempt/check Evidence anchors match
  the unprojected result.

The real-project dogfood records output byte count and reduction versus an
equivalent captured fixture. It does not claim a universal token estimate.

## 6. Test contract and fail-first order

| Test | Story | Type | Fail-first contract |
| --- | --- | --- | --- |
| `TC-0184` | `US-0082` | integration | no-progress stdout/shape/state baseline remains exact |
| `TC-0185` | `US-0082` | integration | JSONL progress is ordered on stderr and stdout is one JSON |
| `TC-0186` | `US-0082` | unit | long fake check emits bounded sanitized heartbeat with injected time |
| `TC-0187` | `US-0082` | integration | pass/fail/timeout/spawn/sink failure never reports a false completion |
| `TC-0188` | `US-0083` | integration | actual summary retains all proof and recovery anchors |
| `TC-0189` | `US-0083` | unit | large actual result is bounded, counted, and deterministic |
| `TC-0190` | `US-0083` | integration | projection has zero effect on durable packet/attempt/Evidence/event state |
| `TC-0191` | `US-0083` | integration | no-flag shape is compatible and invalid flags fail before mutation |
| `TC-0192` | `US-0082` | e2e | explicit-target long dogfood shows progress and compact final output |

The implementation sequence starts by making the targeted tests fail for the
current reasons:

1. actual projection flags are rejected;
2. no progress option exists;
3. the synchronous check loop has no callback or heartbeat;
4. actual projection leaves large nested result sections unbounded.

Tests must not use real multi-minute sleeps. Reporter tests inject time/wait
behavior, and integration checks use short deterministic commands.

## 7. Minimal implementation milestones

### Milestone A — compact actual projection

Candidate files:

- `src/pcl/finish_output.py`;
- `src/pcl/planning_handlers.py`;
- `src/pcl/parser_planning.py`;
- `tests/test_finish.py`.

Steps:

1. save the exact no-flag actual result shape as a regression baseline;
2. change output-flag validation to accept actual `--emit-packet`;
3. add a pure actual-result projector after `emit_finish_packet`;
4. preserve exit code and all durable proof anchors;
5. add size, pagination, display-only, mutation-parity, and invalid-input tests;
6. commit this independently if targeted and full verification are green.

### Milestone B — finish-local progress reporter

Candidate files:

- a small `src/pcl/finish_progress.py` presentation module;
- `src/pcl/parser_planning.py`;
- `src/pcl/planning_handlers.py`;
- `src/pcl/finish_execution.py`;
- `tests/test_finish.py`;
- a focused `tests/test_finish_progress.py`.

Steps:

1. add fail-first parser, stdout/stderr separation, sequence, heartbeat,
   sanitization, and failure-path tests;
2. implement the formatter/sink and optional callback;
3. wrap each synchronous check with a finish-local heartbeat worker;
4. emit validation/commit/terminal phases from the actual execution path;
5. keep `guarded_process.py` unchanged unless a concrete failing test proves
   the finish-local boundary cannot satisfy the contract;
6. commit this independently if targeted and full verification are green.

### Milestone C — real-project dogfood and closeout

1. use a new explicitly bound PCL Task; never rely on implicit target order;
2. capture the pre-run HEAD/status and unrelated dirty paths;
3. run actual finish with `--progress jsonl --summary
   --exclude-machine-state --json`;
4. confirm heartbeats during the long check and one parseable final stdout
   document;
5. resolve packet/attempt and check Evidence IDs;
6. run strict validate/render and record immutable Evidence;
7. update the continuing friction log with observed residual risks;
8. commit only task-owned changes.

## 8. Verification gate

Each implementation milestone runs:

```text
PYTHONPATH=src pytest <targeted tests>
PYTHONPATH=src pytest
PYTHONPATH=src ruff check .
PYTHONPATH=src python -m pcl --root . validate --strict --json
PYTHONPATH=src python -m pcl --root . render --json
```

The final dogfood additionally verifies:

- exact target binding on every progress record and the final result;
- stdout parses as one JSON document while stderr parses as text or JSONL;
- output byte count and all omission counts;
- stored packet/attempt/check artifacts validate and their hashes resolve;
- no progress-only database event, Evidence, or target mutation exists;
- no unrelated `.claude`, `.playwright-cli`, `.work`, or user-owned path is
  staged or committed.

## 9. Stop conditions

Stop and request a new human decision if any of the following becomes necessary:

- a database migration, new dependency, daemon, hosted service, or external
  write;
- a durable/pollable/resumable progress attempt rather than an ephemeral stream;
- a `completion-packet/v2` or breaking change to packet/attempt/check Evidence;
- a change to no-flag finish JSON, command exit semantics, target routing,
  terminal readiness, timeout recovery, or guarded-process termination;
- raw command output, environment values, raw argv, or secrets in progress;
- progress delivery failure affecting the authoritative completion outcome;
- a default-on progress policy;
- a generic guarded-executor change that is not justified by a dedicated
  fail-first regression;
- a compact projection that cannot preserve repository, Evidence, outcome,
  readiness, transition, and recovery anchors.

## 10. Residual risks after this slice

- Stderr progress is not recoverable after the parent process or terminal dies.
- A heartbeat proves the parent finish process is waiting; it does not prove
  forward progress inside the child check.
- The current host subprocess remains non-sandboxed.
- Full no-flag JSON remains intentionally large for compatibility.
- Cockpit will not automatically ingest the stream in this slice.
- Runner-specific structured output, flake quarantine, historical Evidence
  projection, and normalized attempts remain separate P1 decisions.

## 11. Approval boundary

Plan completion means only:

- this document is committed;
- `US-0082` / `US-0083` remain draft;
- `TC-0184`–`TC-0192` remain planned;
- PCL validate/render succeed;
- no production code or test implementation has started.

Implementation requires an explicit human choice that approves both this plan
and the Story semantics. A request to revise or hold leaves `T-0151` open and
does not change code.
