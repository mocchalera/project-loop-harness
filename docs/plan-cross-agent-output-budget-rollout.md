# Cross-agent output-budget rollout plan

Status: Phase 1 implementation under review; remaining rollout slices deferred
for GitHub Issue #13

Date: 2026-08-31

Repository task: `agent-tasks/0229-cross-agent-output-budget-rollout.md`

Dependency: Issue #8 / task 0228 project-agnostic `pcl exec` runtime

Priority: P1 · Milestone: post-v0.6.0

## Phase 1 implementation status

The current implementation is a read-only vertical slice and does not complete
the rollout plan. It provides the two frozen data contracts, a pure
already-tokenized-argv classifier, one packaged `agent-output-budget` Skill, a
compact global fragment, deterministic projections for all five named hosts,
and the public `pcl agent-output policy|classify|render` commands.

The next implementation slices remain explicitly open:

1. inspect-first installers for supported host files;
2. audit-only Claude and Gemini adapters;
3. bounded audit storage, aggregate report, and retention GC;
4. real cross-host dogfood and rollback/reinstall evidence;
5. an explicit human rollout decision before any rewrite proposal.

No installer, hook, audit storage/report/GC, cross-host adoption claim, or
human rollout decision is included in Phase 1.

## 1. Decision

Project Loop Harness will provide one canonical, host-neutral policy for routing
noisy non-interactive verification commands through `pcl exec`, then render that
policy into the global instruction and audit-hook formats used by Codex, Claude
Code, Gemini CLI, OpenCode, and AGI Cockpit workers.

The first rollout milestone is deliberately limited to:

1. a canonical command-classification contract;
2. one shared `agent-output-budget` Skill;
3. deterministic host-specific instruction projections;
4. inspect-first, reversible installers that default to dry-run;
5. audit-only hooks that never rewrite, block, retry, or alter the observed
   command result;
6. measured real-session dogfood across all target hosts.

Automatic command rewriting is not authorized by this plan. A later Issue may
propose a narrow allowlisted rewrite only after the audit cohort shows zero false
positives and the human explicitly accepts that risk.

## 2. Product boundary

### This repository slice owns

- `agent-output-policy/v1`, including positive and negative command fixtures;
- a pure classifier for already-tokenized argv and conservative observation of
  host command strings;
- the packaged `agent-output-budget` Skill and concise global-rule snippet;
- deterministic rendering for Codex, Claude Code, Gemini CLI, OpenCode, and AGI
  Cockpit;
- dry-run/apply/status/rollback adapters for supported local host files;
- local-only bounded audit records and aggregate reports;
- cross-host dogfood evidence and the next decision gate.

### This repository slice does not own

- a general shell parser;
- aliases that replace `npm`, `pytest`, `cargo`, `go`, or shell built-ins;
- changes to the user's normal interactive terminal behavior;
- automatic command rewriting or blocking;
- raw terminal output capture or upload;
- hosted telemetry, remote configuration, or network synchronization;
- AGI Cockpit generic shell access or raw stderr/stdout projection;
- mutation of external repositories merely to install a global policy;
- proof, Evidence, completion, or lifecycle authority for observed commands.

## 3. Canonical policy

### 3.1 Default route

Use `pcl exec -- <argv...>` when all of the following are true:

- the command is non-interactive;
- its primary useful result is success/failure plus a bounded diagnostic;
- normal success output can be repetitive or large;
- the command is expressed as a direct argv invocation rather than an arbitrary
  shell expression;
- no repository-local instruction explicitly requires a different execution
  surface.

Typical eligible families:

- tests: `pytest`, `python -m pytest`, `npm test`, `npm run test*`, `pnpm test`,
  `yarn test`, `cargo test`, `go test`;
- lint and static analysis: `ruff check`, `eslint`, `npm run lint`, `cargo
  clippy`, `mypy`, `pyright`;
- type checks: `tsc --noEmit`, `npm run typecheck`, project `check` scripts;
- builds: `python -m build`, `npm run build`, `cargo build`, package builds;
- project validation: scripts named `validate`, `verify`, `verify:*`, `check`,
  or local-CI equivalents;
- exact non-interactive package installation forms: `pip install --no-input`,
  `python -m pip install --no-input`, and `go install`; plus verbose deterministic
  code generation when the resulting output is not itself the requested artifact.
  Installers that may prompt remain negative.

The policy must support repository-declared exact argv additions without
turning arbitrary shell text into executable policy.

### 3.2 Do not route automatically

The following are deterministic negative cases:

- file/content reads: `cat`, `sed`, `head`, `tail` used to inspect content;
- searches: `rg`, `grep`, `find` when returned matches are the requested data;
- source review: `git diff`, `git show`, `git log`;
- reports whose complete output must be read by the agent;
- prompts, REPLs, interactive installers, password entry, or TTY-dependent
  commands;
- watch mode, development servers, `tail -f`, and other long-lived streaming
  processes;
- arbitrary pipelines, redirections, substitutions, here-documents, compound
  expressions, standalone background operators, or shell functions;
- commands whose command line cannot be safely reduced to an argv shape;
- any command explicitly marked `output_is_artifact` by repository policy.

A negative or unknown classification means "leave unchanged". It never means
"run through a shell and hope the reconstruction is equivalent."

### 3.3 Result-handling rule

- On `PASS`, accept the typed result and do not open diagnostics merely to
  reconfirm success.
- On non-PASS, inspect the bounded presentation first. Use `pcl exec show
  <run-id> --errors` or a bounded tail only when needed.
- Never read or inject a complete raw log into model context by default.
- Never automatically retry a failed command. If a human or higher-level flow
  explicitly retries, retain and report the first failure.
- Do not call a successful retry `PASS` for the whole sequence unless a separate
  contract records the earlier failure and classifies the sequence honestly.

## 4. Contract surfaces

### 4.1 `agent-output-policy/v1`

The packaged policy is data, not executable shell text. It contains:

```json
{
  "schema": "agent-output-policy/v1",
  "eligible_argv_rules": [],
  "negative_argv_rules": [],
  "unsafe_shell_markers": ["|", ">", ">>", "<", "$(", "`", "&&", "||", ";", "&", "\n", "\r", "heredoc", "function"],
  "result_handling": {
    "pass_reads_diagnostics": false,
    "automatic_retry": false,
    "raw_log_upload": false
  }
}
```

Rules use exact executable/subcommand/script-name fields and bounded regular
expressions where necessary. Every rule has a stable `reason_code` and fixture.
Unknown fields fail validation.

### 4.2 Classification result

```json
{
  "schema": "agent-output-classification/v1",
  "classification": "eligible",
  "reason_code": "npm_run_verify_script",
  "recommended_argv_prefix": ["pcl", "exec", "--"],
  "may_rewrite": false
}
```

Allowed classifications:

- `eligible` — instructions should route an explicit argv invocation through
  `pcl exec`;
- `negative` — output or interaction semantics make wrapping inappropriate;
- `unknown` — insufficient evidence; leave unchanged;
- `already_wrapped` — direct `pcl exec` use detected.

`may_rewrite` is always `false` in task 0229.

### 4.3 Audit record

Audit-only hooks write local records such as:

```json
{
  "schema": "agent-output-audit/v1",
  "observed_at": "2026-08-31T00:00:00Z",
  "host": "claude-code",
  "tool": "Bash",
  "classification": "eligible",
  "reason_code": "pytest_direct",
  "already_wrapped": false,
  "action": "observed_only",
  "command_shape_sha256": "sha256:..."
}
```

The record contains no raw output, full command string, secrets, environment
values, current working directory, repository URL, or absolute path. A bounded
sanitized argv shape may be included only if fixtures prove it cannot contain
free-form argument values.

Default audit state:

```text
~/.local/state/project-loop-harness/agent-output-audit/
```

Default retention is 14 days and 32 MiB total, oldest first. The report surface
aggregates counts and reason codes without exposing individual sensitive
arguments.

## 5. Public CLI proposal

```bash
pcl agent-output policy --json
pcl agent-output classify --argv-json '["npm","run","verify:full"]' --json
pcl agent-output render --host codex
pcl agent-output render --host claude
pcl agent-output render --host gemini
pcl agent-output render --host opencode
pcl agent-output render --host cockpit

pcl agent-output install --host codex --dry-run --json
pcl agent-output install --host codex --apply --json
pcl agent-output status --host codex --json
pcl agent-output rollback --host codex --dry-run --json
pcl agent-output rollback --host codex --apply --json

pcl agent-output hook --host claude --event pre-tool-use
pcl agent-output hook --host gemini --event before-tool
pcl agent-output audit report --json
pcl agent-output audit gc --dry-run --json
```

`install` and `rollback` default to dry-run even when `--dry-run` is omitted.
Mutation requires an explicit `--apply`. There is no `--force` shortcut in the
first slice.

## 6. Canonical Skill and global rule

The source Skill is packaged once and rendered consistently:

```text
src/pcl/templates/agent-output-budget/SKILL.md
```

The Skill must remain short and host-neutral. It includes:

- the eligible/negative distinction;
- direct argv examples;
- PASS/non-PASS behavior;
- no raw-log upload;
- no automatic retry;
- recovery commands;
- a statement that host hooks are audit-only.

The always-loaded global snippet is smaller than the Skill. It states only the
default route and points to the Skill/public CLI for procedure. Do not duplicate
long command matrices across five host files.

## 7. Host projections

### 7.1 Codex

Managed global instruction target:

```text
~/.codex/AGENTS.md
```

The adapter inserts or updates one marker-bounded Markdown block. It does not
replace an existing `AGENTS.override.md`, infer user intent from unrelated
instructions, or mutate project-local `AGENTS.md` files.

Codex does not receive an enforcement hook in this slice. Compliance is
instruction/Skill based and measured by session review or supported local tool
observations.

### 7.2 Claude Code

Managed targets:

```text
~/.claude/CLAUDE.md
~/.claude/settings.json
```

The Markdown target receives the same canonical managed block. The settings
adapter adds one uniquely identified `PreToolUse` audit hook for the Bash tool.
The hook reads the documented JSON event, classifies conservatively, records an
observation, and returns an allow/no-change result. It never edits tool input,
denies execution, or emits model-facing raw command content.

### 7.3 Gemini CLI

Managed targets:

```text
~/.gemini/GEMINI.md
~/.gemini/settings.json
```

The Markdown target receives the canonical block. The settings adapter adds one
managed `BeforeTool` audit hook. It uses the documented hook JSON protocol,
returns unchanged continuation, and never modifies tool arguments.

### 7.4 OpenCode

Managed target:

```text
~/.config/opencode/AGENTS.md
```

The first slice uses instruction/Skill projection only unless the installed
OpenCode version exposes a stable audit-hook contract that is fixture-tested.
Do not invent a hook or add an undocumented plugin solely for parity.

### 7.5 AGI Cockpit

The Cockpit projection is a bounded worker-guidance artifact and typed result
mapping. It does not add generic command execution to the Cockpit MCP surface.
Workers execute locally through their existing host and report only:

- run ID;
- typed status and child exit;
- duration;
- raw/exposed byte counts;
- bounded failed checks;
- diagnostic availability/truncation.

Raw stdout, raw stderr, absolute local paths, and retained diagnostic bodies are
not projected to Viewer/Operator/Controller tools by default.

## 8. Safe file mutation

Every local installer follows the same sequence:

1. resolve the documented target without following an ambiguous symlink chain;
2. read and hash the current file;
3. parse the format before proposing a change;
4. render a deterministic diff;
5. return without mutation by default;
6. on `--apply`, recheck the hash immediately before writing;
7. create an owner-only backup and install receipt;
8. write atomically with mode preservation;
9. reparse and verify the managed content;
10. report exact rollback instructions.

Markdown uses stable markers:

```text
<!-- PCL:agent-output-budget:v1:start -->
...
<!-- PCL:agent-output-budget:v1:end -->
```

JSON files use a unique managed hook command and exact structural matching. The
adapter must not reorder unrelated JSON arrays/objects unnecessarily. Unknown
or invalid existing syntax fails closed with no write.

Backups and receipts stay local and bounded. They are not committed or uploaded.
Rollback removes only the exact managed block/hook whose installed hash matches
the receipt; drift requires a new dry-run and human review.

## 9. Audit-only host behavior

Audit hooks are observational:

- exit zero for ordinary observations;
- preserve the host's command and exit semantics;
- never add `pcl exec` to tool input;
- never invoke the observed command themselves;
- never retry;
- never block on audit storage failure;
- write no stdout unless the host protocol requires a bounded valid response;
- write diagnostic failures only to a bounded local error record;
- classify complex/unknown shell text as `unknown`.

The hook implementation must be fast enough not to create material tool latency.
A frozen benchmark records p50/p95 local classifier latency; the target is p95
below 20 ms excluding host process startup. Missing that target is reported, not
hidden.

## 10. Implementation slices

### A. Contract and classifier

- add policy, classification, audit schemas/validators and positive/negative
  fixtures;
- implement pure argv classification;
- add conservative host-string observation with `unknown` as the default;
- freeze reason codes, unsafe shell markers, and no-rewrite invariants;
- add security and fuzz-style bounded-input tests.

### B. Skill and deterministic rendering

- add one canonical Skill and compact global snippet;
- render all five host projections from the same source data;
- add snapshot/parity tests preventing semantic drift;
- include packaged source/wheel/sdist parity.

### C. Inspect-first installers

- implement target discovery, dry-run diff, hash recheck, owner-only backup,
  atomic apply, status, and rollback;
- test missing files, valid existing content, duplicate managed blocks, drift,
  invalid JSON, symlinks, permissions, concurrent updates, and interrupted
  writes;
- ensure project-local files are not touched by a global-host install.

### D. Audit-only hooks

- implement Claude and Gemini documented hook adapters;
- keep Codex and OpenCode instruction-only unless a stable documented audit
  surface is available and separately fixture-tested;
- add local bounded audit storage/report/GC;
- prove no command mutation, blocking, retry, output capture, or result change.

### E. Cross-host dogfood

- install through dry-run then explicit apply on the maintainer machine;
- record before/after hashes and rollback verification without committing file
  contents;
- run real sessions on Codex, Claude Code, Gemini CLI, OpenCode, and one AGI
  Cockpit worker path;
- measure eligible commands, wrapped commands, misses, false positives, false
  negatives, diagnostic reads, hook latency, and configuration conflicts;
- roll back and reinstall at least one Markdown host and one JSON-hook host.

### F. Decision gate

The result report chooses one:

- `policy-only` — keep instructions/Skill and remove audit hooks;
- `continue-audit` — retain audit-only mode and collect more evidence;
- `propose-narrow-rewrite` — open a separate Issue with exact allowlisted rules
  and explicit human authorization.

The task cannot select the third outcome merely because implementation is
possible. The observed evidence and human decision are required.

## 11. Test matrix

- exact eligible argv across Python, Node, Rust, and Go families;
- negative content/search/diff/report commands;
- interactive/watch/server/streaming examples;
- pipelines, redirections, substitutions, compound expressions, newlines, and
  malformed quoting;
- already-wrapped commands;
- secret-shaped values, very long argv, binary/invalid hook input, and absolute
  local paths;
- deterministic render parity for all hosts;
- Markdown marker insertion/update/removal and duplicate detection;
- JSON hook merge, invalid syntax, unrelated-entry preservation, and rollback;
- symlink/no-follow, owner modes, atomic write, crash, concurrent drift, and
  backup retention;
- audit storage failure that leaves host execution unchanged;
- source, wheel, and sdist installed CLI behavior;
- real host fixture payloads for Claude and Gemini;
- proof that hook responses never request deny, modify, retry, or replace.

## 12. Acceptance summary

- one canonical policy and Skill, not five drifting copies;
- deterministic positive and negative classification;
- dry-run by default and reversible local installation;
- audit-only hooks with no execution side effects;
- no raw output or sensitive command persistence;
- truthful host support rather than fabricated parity;
- measured use across all five target host paths;
- explicit human gate before any automatic rewriting;
- no claim that the whole environment is configured until the actual local
  files are installed, read back, and verified.
