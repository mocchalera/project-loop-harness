# 0229 — Cross-agent output-budget default rollout

Status: **proposed / not started**. Implement only after GitHub Issue #13 and
`docs/plan-cross-agent-output-budget-rollout.md` are accepted on `main`, and
after task 0228 has a merged two-family dogfood closeout.

Priority: P1 · Milestone: post-v0.6.0 · Origin: GitHub Issue #13

## Problem

The project-agnostic `pcl exec` runtime is available, but noisy verification
commands are not yet routed through it by default across Codex, Claude Code,
Gemini CLI, OpenCode, and AGI Cockpit workers. Repeating instructions by hand or
copying wrappers into repositories will drift. Broad shell aliases or automatic
rewriting could change semantics for searches, diffs, interactive commands,
watch mode, servers, pipelines, and output-as-artifact commands.

## Goal

Create one canonical policy and shared Skill, render deterministic host-specific
global instructions, provide inspect-first reversible installers, and introduce
audit-only hooks that measure missed routing without modifying execution.

The terminal decision is whether to keep policy-only, continue audit-only, or
open a separate narrowly scoped rewrite proposal. This task does not authorize
automatic rewriting.

## Scope

Implement the frozen contract in
`docs/plan-cross-agent-output-budget-rollout.md`:

- `agent-output-policy/v1`;
- `agent-output-classification/v1`;
- `agent-output-audit/v1`;
- pure tokenized-argv classification and conservative host-string observation;
- one packaged `agent-output-budget` Skill and compact global rule;
- deterministic renderers for Codex, Claude Code, Gemini CLI, OpenCode, and AGI
  Cockpit;
- dry-run/apply/status/rollback adapters for supported global host files;
- Claude and Gemini audit-only hooks using documented event protocols;
- bounded local audit report and retention cleanup;
- real-session dogfood and an explicit human decision gate.

## Invariants — what to protect

- `pcl exec` remains the only command executor in this feature; classifiers and
  hooks never invoke an observed command themselves.
- Classification is advisory. `unknown` and `negative` leave commands unchanged.
- No automatic rewrite, deny, block, retry, or exit-status modification.
- No aliases replacing `npm`, `pytest`, `cargo`, `go`, shell built-ins, or the
  user's normal terminal.
- Do not parse/reconstruct arbitrary shell syntax. Complex strings fail closed
  to `unknown`.
- Searches, diffs, file reads, interactive tools, watch mode, servers,
  streaming commands, and output-as-artifact reports remain unwrapped by
  default.
- PASS does not trigger diagnostic reads. Non-PASS starts with bounded output
  and retains the first failure.
- Audit records contain no raw output, full command string, environment values,
  repository URL, current working directory, secrets, or absolute local paths.
- Installers default to dry-run. Mutation requires explicit `--apply`.
- Existing host files are parsed, hashed, diffed, backed up, atomically updated,
  read back, and reversible without replacing unrelated content.
- Invalid syntax, ambiguous symlinks, concurrent drift, or duplicate managed
  regions fail closed with no write.
- AGI Cockpit receives typed summaries and opaque run IDs only; no generic shell
  or raw terminal projection is added.
- No network, telemetry, upload, external notification, project lifecycle
  mutation, Evidence creation, or completion/proof authority.
- Source, wheel, and sdist expose the same policy, Skill, renderers, and CLI
  contract.

## Non-scope

- Reimplementing task 0228 or changing `agent-exec-result/v1` without a separate
  compatibility decision.
- Automatic command rewriting or a rewrite-enabled hook.
- A general shell parser, shell sandbox, remote executor, daemon, or hosted
  configuration service.
- Installing project-local `AGENTS.md`, `CLAUDE.md`, or repository configuration
  as part of a global-host operation.
- Uploading raw logs or audit records to GitHub, Slack, Fumiori, Drive, or
  Cockpit.
- Claiming full-environment adoption before the actual local host files are
  installed and verified.
- Fabricating Codex/OpenCode hook parity where no stable documented audit
  contract is available.
- Superseding Issue #6 onboarding or Issue #2 external adoption proof.

## Implementation slices

### A. Contract and classifier

Freeze policy/classification/audit schemas, stable reason codes, positive and
negative fixtures, unsafe shell markers, and no-rewrite assertions. Implement a
pure argv classifier; host command strings remain `unknown` unless an exact
safe shape is available from the host event.

### B. Skill and host rendering

Add the single canonical Skill and compact always-loaded snippet. Render all
five host projections from the same source data and add semantic parity
snapshots. Package them in source, wheel, and sdist.

### C. Inspect-first installers

Implement dry-run diff, explicit apply, hash recheck, owner-only backup,
atomic/no-follow write, status, and exact managed-content rollback. Preserve
unrelated Markdown and JSON content and modes.

### D. Audit-only hooks

Implement documented Claude `PreToolUse` and Gemini `BeforeTool` adapters. They
classify, record a bounded local observation, and return unchanged continuation.
Codex and OpenCode remain instruction-only unless stable documented audit
surfaces are fixture-bound.

### E. Cross-host dogfood

Use actual Codex, Claude Code, Gemini CLI, OpenCode, and AGI Cockpit worker
sessions. Record routing rate, misses, false positives/negatives, bounded
diagnostic reads, hook p50/p95 latency, configuration conflicts, and verified
rollback/reinstall for at least one Markdown and one JSON target.

### F. Human decision

Publish a bounded report and obtain one explicit outcome:

- `policy-only`;
- `continue-audit`;
- `propose-narrow-rewrite` in a separate Issue.

## Test contract

- [ ] Eligible argv fixtures cover Python, Node, Rust, and Go verification
      families.
- [ ] Negative fixtures cover searches, diffs, file reads, reports,
      interactive/watch/server/streaming commands, and output-as-artifact cases.
- [ ] Pipelines, redirections, substitutions, compound strings, malformed
      quoting, and newlines classify as `unknown` and remain unchanged.
- [ ] Already-wrapped commands are detected without nesting `pcl exec`.
- [ ] Secret-shaped, oversized, path-bearing, binary, and invalid hook inputs
      cannot leak sensitive values into audit records or responses.
- [ ] Every classification has a stable reason code and deterministic result.
- [ ] All host projections remain semantically identical to the canonical
      policy/Skill.
- [ ] Dry-run never writes; apply requires an exact pre-write hash recheck.
- [ ] Markdown managed blocks are idempotent and duplicate-safe.
- [ ] JSON hook entries preserve unrelated configuration and fail closed on
      invalid syntax.
- [ ] Symlink, permission, concurrent-drift, partial-write, backup, and rollback
      cases are covered.
- [ ] Audit storage failure never blocks or changes the observed command.
- [ ] Hook responses never request deny, modify, replace, retry, or output
      capture.
- [ ] Source, installed wheel, and installed sdist behavior agree.
- [ ] Real dogfood covers all five target host paths.

## Whole-task acceptance criteria

- [ ] All schemas, policy rules, negative boundaries, and managed-file contracts
      are documented and fixture-frozen.
- [ ] One canonical Skill and global snippet generate all host projections.
- [ ] Codex, Claude Code, Gemini CLI, OpenCode, and Cockpit guidance agree on
      eligible commands and result handling.
- [ ] Installers are dry-run by default, preserve unrelated content, and have a
      verified rollback path.
- [ ] Audit-only hooks produce no execution side effects and persist no raw
      output or sensitive context.
- [ ] The frozen negative corpus and real sessions have zero false-positive
      routing classifications.
- [ ] Cross-host evidence reports misses, false negatives, diagnostic reads,
      latency, conflicts, and rollback results honestly.
- [ ] The human records one terminal rollout decision before any rewrite work is
      opened.
- [ ] No whole-environment adoption claim is made until actual local files are
      installed, read back, and verified.
