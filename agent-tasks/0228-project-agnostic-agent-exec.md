# 0228 — Project-agnostic `pcl exec` and bounded agent output

Status: **done / accepted**. Runtime implementation merged through PR #12 at
`df94bf9c5315f92cbc0847b72e074d89dd2d786b`. Exact-commit CI and the Python plus
Node/TypeScript dogfood are recorded in
`docs/evidence/0250-agent-exec-dogfood.md`.

Priority: P1 · Milestone: post-v0.6.0 · Origin: GitHub Issue #8

## Problem

No prior public PCL command provided low-ceremony, project-agnostic execution for
a single noisy verification command. Existing workflow, finish, and proof
surfaces have stronger project/lifecycle authority and could not be repurposed
as a generic wrapper. Per-repository scripts would duplicate the guarded
executor and drift across agent hosts.

The prior guarded process retained only a bounded head for each output stream,
which could hide a useful failure in the middle or tail of a large agent-facing
command result.

## Goal

Add a lightweight `pcl exec` surface that works without `pcl init`, preserves
the child command outcome, emits compact deterministic presentation, and keeps
only bounded redacted local diagnostics. It grants no PCL lifecycle, Evidence,
proof, promotion, publication, or external-write authority.

## Delivered scope

The implementation follows
`docs/plan-project-agnostic-agent-exec.md` and provides:

- `pcl exec -- <argv...>` and machine-readable `--json` output;
- `pcl exec show <run-id> --errors|--tail <n>`;
- `pcl exec meta <run-id> --json`;
- `pcl exec gc [--dry-run]`;
- `agent-exec-result/v1` schema, validator, and fixtures;
- bounded head, rolling tail, and streaming error-window diagnostics;
- owner-only redacted local metadata/diagnostic storage;
- source, wheel, and sdist parity;
- Python and Node/TypeScript real-repository dogfood.

## Preserved invariants

- The child is invoked as argv with `shell=False`; shell syntax is not parsed or
  reconstructed.
- Child exit and signal outcomes are preserved; timeout, infrastructure error,
  and interruption mappings are explicit and fixture-bound.
- Execution does not create `.project-loop`, open or mutate a project database,
  append an Event, create Evidence, render, or change Goal/Task/Feature/Story/Test
  state.
- The existing guarded spawn, environment allowlist, timeout/process-group,
  redaction, and observability primitives are reused rather than forked.
- stdout and stderr are independently drained with bounded memory and no observed
  deadlock.
- PASS output is at most 5 lines / 2 KiB; non-PASS output is at most 120 lines /
  24 KiB.
- Unredacted output is not persisted by default. PASS stores metadata only.
- Local state is owner-only, no-follow/exclusive where available, capped, and
  retention-bounded.
- There is no automatic retry. A later explicit retry cannot erase the first
  failure.
- Existing `workflow guard`, `loop execute`, `finish`, and proof execution
  contracts remain compatible.
- No network, telemetry, upload, notification, or raw-log indexing is introduced.

## Explicit non-scope

- Global Codex, Claude Code, Gemini CLI, OpenCode, or AGI Cockpit configuration.
- Automatic command interception or rewriting.
- Shell pipelines, redirections, command substitution, interactive/watch/server
  support, or full-log dumping.
- Native reporter replacement.
- Database migration, daemon, hosted state, remote execution, or sandbox claims.
- Changes to compact finish output or durable finish-attempt recovery.
- Reprioritizing or superseding GitHub Issues #2, #3, or #6.

The separate global rollout is owned by GitHub Issue #13 and task 0229.

## Implementation record

### A. Contract and characterization — complete

`agent-exec-result/v1`, status/exit mapping, argv disclosure, artifact metadata,
and positive/negative fixtures are frozen. Existing guarded-process callers were
characterized and retained through regression coverage.

### B. Bounded diagnostic capture — complete

The guarded process supports optional bounded head, rolling tail, and diagnostic
chunk observers while maintaining independent stdout/stderr drainage. Streaming
error windows retain failures located outside the head/tail budget. The
implementation records extraction strategy, counts, truncation, redaction, and
termination metadata.

### C. CLI and local retention store — complete

Project-agnostic parser, handlers, service, opaque run IDs, owner-only local
storage, bounded inspection, and age/size GC are implemented without project-root
initialization or lifecycle mutation.

### D. Distribution and dogfood — complete

Source, wheel, installed wheel, and installed sdist behavior are covered. The
accepted dogfood observations are:

| Family / command | Result | Raw bytes | Exposed | Reduction | Follow-up reads | False classifications |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Python `pytest` | PASS | 13,399 | 89 bytes / 1 line | 99.3358% | 0 | 0 |
| Python `python -m build` | PASS | 167,873 | 87 bytes / 1 line | 99.9482% | 0 | 0 |
| Node `npm run verify:full` | PASS | 81,201 | 87 bytes / 1 line | 99.8929% | 0 | 0 |

A shallow-checkout protocol defect produced a genuine Python test failure. The
runtime returned `FAIL` truthfully, and one bounded `show --errors` read exposed
the missing historical commit without requiring a raw log. Full-history rerun
then passed. Both outcomes remain recorded in evidence.

## Test contract

- [x] 6,500-line PASS exposes <= 5 lines and <= 2 KiB.
- [x] Head, middle, and tail failures remain visible within 120 lines / 24 KiB.
- [x] Large simultaneous stdout/stderr is drained without deadlock.
- [x] UTF-8 boundary, invalid byte, and binary cases are safe and deterministic.
- [x] Spawn failure, timeout, interruption, exit code, and signal cases are exact.
- [x] Descendant/process-group cleanup uncertainty is reported honestly.
- [x] Secret-shaped output and sensitive-shaped argv do not leak into exposed or
      persisted diagnostics in the frozen fixtures.
- [x] Symlink/no-follow, file mode, partial-write, collision, and cleanup faults
      fail safely.
- [x] Execution outside a repository creates no project-local PCL state.
- [x] Age and total-byte retention limits are enforced oldest-first.
- [x] Existing guarded workflow, finish, and proof suites remain green.
- [x] Source, wheel, and sdist interfaces agree.

## Whole-task acceptance criteria

- [x] Public, machine, and storage contracts are documented and fixture-frozen.
- [x] `pcl exec` is project-agnostic, bounded, and truth-preserving.
- [x] Useful failure diagnostics survive head, middle, and tail placement.
- [x] Local diagnostics are redacted, owner-only, and retention-bounded.
- [x] No PCL project/lifecycle/proof authority is created or mutated.
- [x] Two-family dogfood is recorded without an external-adoption claim.
- [x] The human decision is to proceed to policy, Skill, reversible installers,
      and audit-only host rollout under Issue #13.

## Final decision

Accept task 0228 as complete. Proceed to task 0229 in audit-first mode. Do not
authorize broad shell aliases or automatic command rewriting from this result,
and do not claim whole-environment adoption until the actual local host files
are installed and verified.
