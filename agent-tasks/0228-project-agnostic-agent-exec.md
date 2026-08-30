# 0228 — Project-agnostic `pcl exec` and bounded agent output

Status: **implementation under review**. The runtime, contract, packaging checks,
and documentation are implemented on the Issue #8 feature branch. Keep Issue #8
open until real Python and Node/TypeScript repository dogfood records the measured
result and a human decides whether the global-policy/audit-hook rollout should
begin.

Priority: P1 · Milestone: post-v0.6.0 · Origin: GitHub Issue #8

## Problem

No current public PCL command provides low-ceremony, project-agnostic execution
for a single noisy verification command. Existing workflow, finish, and proof
surfaces have stronger project/lifecycle authority and must not be repurposed as
a generic wrapper. Per-repository scripts would duplicate the guarded executor
and drift across agent hosts.

The existing guarded process keeps only a bounded head for each output stream.
That is adequate for current Evidence contracts but can hide a failure in the
middle or tail of a large agent-facing command result.

## Goal

Add a lightweight `pcl exec` surface that works without `pcl init`, preserves
the child command outcome, emits compact deterministic presentation, and keeps
only bounded redacted local diagnostics. It grants no PCL lifecycle, Evidence,
proof, promotion, publication, or external-write authority.

## Scope

Implement the frozen contract in
`docs/plan-project-agnostic-agent-exec.md`:

- `pcl exec -- <argv...>` and `--json`;
- `pcl exec show <run-id> --errors|--tail <n>`;
- `pcl exec meta <run-id> --json`;
- `pcl exec gc [--dry-run]`;
- `agent-exec-result/v1` schema, validator, and fixtures;
- bounded head/rolling-tail/error-window diagnostic capture;
- owner-only redacted local metadata/diagnostic storage;
- source/wheel/sdist parity and two-family dogfood evidence.

## Invariants — what to protect

- Invoke argv directly with `shell=False`; do not parse or reconstruct shell
  syntax.
- Preserve the child exit/signal outcome; timeout/infra/interruption mappings
  are explicit and fixture-bound.
- Do not create `.project-loop`, open or mutate a project database, append an
  Event, create Evidence, render, or change Goal/Task/Feature/Story/Test state.
- Reuse the existing guarded spawn, environment allowlist, timeout/process-group,
  redaction, and observability primitives; do not fork a second executor.
- stdout/stderr drainage stays bounded and deadlock-free.
- PASS output is at most 5 lines / 2 KiB; non-PASS output is at most 120 lines /
  24 KiB.
- Do not persist unredacted output by default. PASS stores metadata only.
- Local state is owner-only, no-follow/exclusive where applicable, capped, and
  retention-bounded.
- No automatic retry. A later explicit retry cannot erase the first failure.
- Existing `workflow guard`, `loop execute`, `finish`, and proof execution
  result shapes and authority remain compatible.
- No network, telemetry, upload, external notification, or raw-log indexing.

## Non-scope

- Global Codex/Claude/Gemini/OpenCode rule or hook installation.
- AGI Cockpit tool/schema changes.
- Automatic command interception or classification enforcement.
- Shell pipelines, redirections, command substitution, interactive/watch/server
  support, or full-log dumping.
- Native reporter replacement.
- Database migration, daemon, hosted state, remote execution, or sandbox claims.
- Changes to compact finish output or durable finish-attempt recovery.
- Reprioritizing or superseding GitHub Issues #2, #3, or #6.

## Implementation slices

### A. Contract and characterization

Freeze `agent-exec-result/v1`, status/exit mapping, argv disclosure, artifact
metadata, and positive/negative fixtures. Characterize all current callers of
`execute_guarded_process` before internal capture changes.

### B. Bounded diagnostic capture

Add bounded head, rolling tail, and candidate error windows while independently
draining stdout/stderr. Return deterministic extraction strategy, counts,
truncation reasons, and redaction/hash metadata. Preserve current callers through
regression fixtures.

### C. CLI and local retention store

Add project-agnostic parser/handler/service modules, opaque run IDs, owner-only
atomic/no-follow storage, `show`, `meta`, and deterministic age/size GC. Cleanup
failure is advisory and never changes the child result.

### D. Distribution and dogfood

Verify source, wheel, installed wheel, and installed sdist. Run one Python and
one Node/TypeScript repository command and publish bounded evidence with
raw/exposed bytes, reduction ratio, follow-up reads, false classification, and
security findings. Record a human decision on global-policy/audit-hook rollout.

## Test contract

- [ ] 6,500-line PASS exposes <= 5 lines and <= 2 KiB.
- [ ] Head, middle, and tail failures remain visible within 120 lines / 24 KiB.
- [ ] Large simultaneous stdout/stderr cannot deadlock.
- [ ] UTF-8 boundary, invalid byte, and binary cases are safe and deterministic.
- [ ] Spawn failure, timeout, interruption, exit code, and signal cases are exact.
- [ ] Descendant/process-group cleanup uncertainty is reported honestly.
- [ ] Secret-shaped output and sensitive-shaped argv do not leak into exposed or
      persisted artifacts.
- [ ] Symlink/no-follow, file mode, partial-write, collision, and cleanup faults
      fail safely.
- [ ] Execution outside a repository creates no project-local PCL files/state.
- [ ] Age and total-byte retention limits are enforced oldest-first.
- [ ] Existing guarded workflow, finish, and proof suites remain green.
- [ ] Source/wheel/sdist interfaces and fixtures agree.

## Whole-task acceptance criteria

- [ ] All public and storage contracts are documented and fixture-frozen.
- [ ] `pcl exec` is project-agnostic, bounded, and truth-preserving.
- [ ] Useful failure diagnostics survive head/middle/tail placement.
- [ ] Local diagnostics are redacted, owner-only, and retention-bounded.
- [ ] No PCL project/lifecycle/proof authority is created or mutated.
- [ ] Two-family dogfood is recorded without an external-adoption claim.
- [ ] A separate human decision determines whether host-global rollout begins.
