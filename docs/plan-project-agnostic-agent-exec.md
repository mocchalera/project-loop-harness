# Project-agnostic agent execution and output-budget plan

Status: proposed for GitHub Issue #8

Date: 2026-08-30

Repository task: `agent-tasks/0228-project-agnostic-agent-exec.md`

Priority: P1 · Milestone: post-v0.6.0

## 1. Decision

Project Loop Harness will provide one lightweight, project-agnostic execution
surface for noisy non-interactive verification commands:

```text
agent -> pcl exec -> guarded process -> compact result -> bounded local diagnostics
```

The command preserves execution truth while limiting what is returned to model
context. It must work without `pcl init` and must not create project-local PCL
state.

The runtime belongs in PCL because the repository already owns guarded argv
execution, timeout and process-group handling, environment allowlisting,
stdout/stderr draining, redaction, and execution metadata. A standalone
`agent-run` wrapper or copied per-repository script would create a second
executor and drift across tools.

## 2. Product boundary

### This repository slice owns

- public `pcl exec` run/inspect/retention commands;
- `agent-exec-result/v1`;
- bounded diagnostic extraction and local storage;
- source/wheel/sdist parity;
- focused dogfood evidence;
- concise packaged guidance explaining when agents should use the command.

### This repository slice does not own

- global host configuration under `~/.codex`, `~/.claude`, `~/.gemini`, or
  `~/.config/opencode`;
- host hook rewriting or command interception;
- AGI Cockpit raw-terminal access or external log transport;
- Fumiori, Slack, Drive, or GitHub log indexing;
- changes to PCL lifecycle, Evidence, completion, or proof authority.

Those are downstream rollout concerns after this runtime is accepted and
measured. The first implementation must not claim that the maintainer's whole
development environment has adopted the default.

## 3. Relationship to existing execution surfaces

Current execution surfaces remain authoritative for their domains:

| Surface | Responsibility | This plan must not change |
| --- | --- | --- |
| `pcl workflow guard` | approved workflow command planning/execution | workflow contracts, Evidence, result shape |
| `pcl loop execute` | workflow/agent-step orchestration | run/job lifecycle and completion behavior |
| `pcl finish --emit-packet` | project checks and proof-backed completion | packet, attempt, target transition, compact-output/progress contracts |
| proof workspace/execution | authority-bound isolated proof | candidate identity, proof packets, admission rights |
| `pcl exec` | low-ceremony observation of one argv command | no lifecycle or proof authority |

`pcl exec` may reuse internal guarded-process components. Any internal capture
refactor must retain compatibility fixtures for every existing caller.

## 4. Public CLI contract

### 4.1 Run

```bash
pcl exec -- npm test
pcl exec --json -- npm run verify
pcl exec --timeout-seconds 300 -- cargo test
```

The `--` separator is required. The runtime receives an argv list and invokes
it with `shell=False`.

### 4.2 Inspect

```bash
pcl exec show AX-... --errors
pcl exec show AX-... --tail 80
pcl exec meta AX-... --json
```

The first slice does not expose a generic full-log dump. `show` returns only a
bounded redacted diagnostic view. Pattern search can be considered later if
real dogfood shows that `--errors` and `--tail` are insufficient.

### 4.3 Retention

```bash
pcl exec gc --dry-run
pcl exec gc
```

Cleanup is local-only, deterministic, and oldest-first. Normal execution may
also perform bounded opportunistic cleanup, but cleanup failure must not change
the child command result.

## 5. Result contract

Machine-readable output uses:

```json
{
  "schema": "agent-exec-result/v1",
  "run_id": "AX-20260830-...",
  "status": "PASS",
  "exit_code": 0,
  "signal": null,
  "duration_ms": 8421,
  "command": ["npm", "test"],
  "raw": {"stdout_bytes": 480000, "stderr_bytes": 3221},
  "exposed": {"lines": 1, "bytes": 138},
  "diagnostics": {
    "available": false,
    "truncated": false,
    "strategy": "none"
  },
  "retry_count": 0
}
```

Allowed statuses:

- `PASS` — first execution completed successfully;
- `FAIL` — non-zero child result;
- `TIMEOUT` — timeout budget expired;
- `INFRA_ERROR` — spawn, executable, permission, or unusable-environment error;
- `INTERRUPTED` — caller/host interruption;
- `FLAKY` — reserved for an explicit higher-level retry flow that retains the
  first failure. The base command never retries automatically.

The caller-visible process result preserves the original child exit/signal
semantics wherever the host permits. Typed infrastructure/timeout/interruption
codes must be frozen before implementation and must not collide silently with
ordinary child results.

## 6. Presentation budget

### PASS

Target: one line; hard maximum 5 lines and 2 KiB.

```text
PASS run=AX-... exit=0 duration=8.4s raw=483KB exposed=1L
```

Successful stdout/stderr content is not persisted by default and must not be
opened by an agent merely to reconfirm success.

### Failure

Hard maximum: 120 lines and 24 KiB returned to the caller.

```text
FAIL run=AX-... exit=1 duration=3.9s
failed: tests/policy.test.mjs > rejects stale access decision
AssertionError: expected 'denied', received 'allowed'
diagnostics=37L strategy=error-block+stderr-tail truncated=true
inspect: pcl exec show AX-... --errors
```

## 7. Diagnostic extraction

A head-only bounded stream is insufficient for this surface because the useful
failure may occur after a long successful prefix. The collector must remain
bounded while retaining enough information for deterministic extraction.

Preference order:

1. native structured reporter data, when explicitly configured and safely
   parsed;
2. recognized error/failure blocks with bounded surrounding context;
3. stderr tail;
4. combined stdout/stderr tail with source labels;
5. a small startup/configuration head.

The implementation may use bounded head + rolling tail + bounded candidate
error windows. It must never buffer an unbounded stream in memory. stdout and
stderr remain independently drained to avoid deadlock. Ordering claims must be
honest: exact inter-stream ordering is not asserted unless the execution path
actually records it.

## 8. Storage and security

Default state root:

```text
~/.local/state/project-loop-harness/agent-exec/
  YYYY-MM-DD/
    AX-.../
      meta.json
      diagnostic.redacted.log
```

Rules:

- directory mode `0700`; file mode `0600`;
- no unredacted output persisted by default;
- PASS stores metadata only;
- non-PASS diagnostic artifact capped at 16 MiB;
- default retention: 72 hours and 512 MiB total;
- oldest-first cleanup with a dry-run projection;
- binary output is classified and not persisted as decoded text;
- externally shareable JSON contains no absolute local artifact path;
- no automatic network, telemetry, upload, index, or external notification;
- redaction is defense in depth, not a secret-free proof.

Command argv can itself contain sensitive values. Human output may render a
safely quoted command only after conservative redaction; machine output should
support an omission/hash policy if the argv cannot be safely exposed. The
contract must freeze that behavior before implementation.

## 9. Command classification guidance

Use `pcl exec` for non-interactive commands whose primary result is pass/fail
and whose normal output can be substantial:

- tests;
- lint;
- type checks;
- builds;
- validate/check/verify scripts;
- package installation;
- verbose code generation;
- local CI-equivalent checks.

Do not automatically wrap:

- interactive prompts or REPLs;
- watch mode, servers, or streaming processes;
- file reads, searches, diffs, and reports whose output is the requested data;
- arbitrary pipelines, redirections, substitutions, compound shell strings,
  or shell functions.

This classification is guidance only in the first slice. `pcl exec` executes an
explicit user/agent request; it does not intercept unrelated commands.

## 10. Implementation slices

### A. Contract and fail-first fixtures

- add `agent-exec-result/v1` schema/validator and positive/negative fixtures;
- freeze exit/status mapping, argv disclosure, path omission, storage metadata,
  and truncation fields;
- characterize existing guarded-process callers before refactoring capture.

### B. Bounded diagnostic collector

- reuse guarded process spawn/environment/timeout/redaction primitives;
- add bounded head, rolling tail, and error-window retention;
- preserve independent non-blocking stdout/stderr drainage;
- expose deterministic extraction metadata and hashes;
- prove existing workflow/finish/proof callers remain compatible.

### C. Project-agnostic CLI and local store

- add parser/handler/service modules without requiring project-root discovery;
- generate opaque run IDs;
- write owner-only metadata/diagnostics with no-follow/exclusive semantics;
- implement `show`, `meta`, and bounded `gc`;
- preserve child process result semantics.

### D. Distribution, docs, and dogfood

- source, wheel, installed-wheel, and installed-sdist parity tests;
- public command guide and recovery guidance;
- one Python and one Node/TypeScript real-repository run;
- evidence report measuring raw/exposed bytes, reduction ratio, extra
  diagnostic reads, false classifications, and security findings;
- explicit human decision on whether to proceed to global-policy/audit-hook
  rollout.

## 11. Test matrix

- 6,500-line success;
- failures at head, middle, and tail;
- simultaneous large stdout/stderr deadlock regression;
- UTF-8 split boundaries and invalid/binary bytes;
- executable-not-found and permission-denied spawn errors;
- timeout with a surviving descendant/process-group uncertainty;
- caller interruption;
- exact exit-code/signal behavior;
- secret-shaped stdout/stderr and sensitive-shaped argv;
- symlink/no-follow, permissions, partial-write, and cleanup fault injection;
- concurrent runs and run-ID collision handling;
- age and total-byte cleanup ceilings;
- execution outside a repository with zero project-local state;
- unchanged workflow guard, loop execute, finish, and proof execution fixtures;
- source/wheel/sdist parity.

## 12. Rollout after this Issue

The broader development-environment default is deliberately staged:

1. merge and release the project-agnostic runtime;
2. dogfood explicit `pcl exec` use and measure false classifications;
3. add the canonical global rule and shared skill outside this repository;
4. begin host adapters in audit-only mode;
5. rewrite only exact safe commands after measured evidence;
6. allow AGI Cockpit to carry typed summaries and opaque run IDs, never raw
   terminal output by default.

Each later write surface needs its own Issue/PR and explicit authorization. The
runtime Issue is successful when it creates a trustworthy foundation, not when
it claims all hosts have already adopted it.

## 13. Acceptance summary

- one runtime, no copied wrappers;
- project-agnostic and zero project-state mutation;
- deterministic 5-line/2-KiB PASS budget;
- deterministic 120-line/24-KiB non-PASS budget;
- useful head/middle/tail failure extraction;
- exact, honest execution outcome handling;
- bounded owner-only redacted local diagnostics;
- no automatic retry or hidden initial failure;
- no raw-log external transport;
- existing execution/proof/lifecycle compatibility;
- source/wheel/sdist parity;
- two-family dogfood and an explicit next-stage decision.
