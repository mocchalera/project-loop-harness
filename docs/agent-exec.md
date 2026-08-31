# Bounded agent command execution

`pcl exec` runs one non-interactive argv command without requiring `pcl init`.
It is intended for tests, lint, type checks, builds, validation, package
installation, and other commands whose primary result is success or failure but
whose normal output can be large.

The output-budget policy permits exact non-interactive install forms. Examples are
`pip install --no-input`, `python -m pip install --no-input`, and `go install`.
Installers that may prompt remain outside the bounded route.

It is not a shell alias, workflow engine, project-completion proof, or sandbox.
It grants no Goal, Task, Evidence, completion-packet, proof, publication, or
external-write authority.

## Run a command

Use an explicit `--` separator. Everything after it belongs to the child command,
including arguments named `--json` or `--root`.

```bash
pcl exec -- npm test
pcl exec -- pytest
pcl --json exec --timeout-seconds 300 -- cargo test
```

The child is invoked as an argv list with `shell=False`. Pipelines, redirections,
command substitutions, compound shell strings, REPLs, watch mode, and development
servers are not automatically interpreted or wrapped.

## Output contract

A successful human result is normally one line and is always bounded to five
lines / 2 KiB:

```text
PASS run=AX-... exit=0 duration=8.421s raw=483221B exposed=1L
```

A non-success result is bounded to 120 lines / 24 KiB. It prefers recognized
error blocks, then stderr tail, then a combined bounded tail. The guarded process
retains a bounded head plus a rolling tail so a late failure is not lost behind a
large successful prefix.

```text
FAIL run=AX-... exit=1 duration=3.912s
STDERR | AssertionError: expected denied, received allowed
diagnostics=1L strategy=error-block truncated=true
inspect: pcl exec show AX-... --errors
```

Machine output uses `agent-exec-result/v1`:

```bash
pcl --json exec -- npm test
```

Statuses are `PASS`, `FAIL`, `TIMEOUT`, `INFRA_ERROR`, and `INTERRUPTED`.
`FLAKY` is reserved for a future explicit retry layer. The base command never
retries automatically and therefore cannot erase an initial failure.

## Inspect a retained failure

```bash
pcl exec show AX-... --errors
pcl exec show AX-... --tail 40
pcl --json exec meta AX-...
```

There is no default full-log dump. Inspection remains bounded and redacted.
Successful stdout/stderr content is not retained.

## Local state and retention

Metadata and failure diagnostics are local-only:

```text
~/.local/state/project-loop-harness/agent-exec/
  YYYY-MM-DD/
    AX-.../
      meta.json
      diagnostic.redacted.log   # non-PASS only
```

`PCL_AGENT_EXEC_STATE_DIR` can override the root for an isolated environment or
test. On POSIX systems directories are owner-only (`0700`) and files are
owner-only (`0600`). Writes use exclusive/no-follow behavior where the platform
supports it.

Defaults:

- 72-hour retention;
- 512 MiB total local-state ceiling;
- oldest-first cleanup;
- no network, telemetry, upload, index, or notification;
- no unredacted output persistence;
- no absolute local artifact paths in the public result.

Inspect or apply cleanup:

```bash
pcl exec gc --dry-run
pcl exec gc
```

Unexpected files or symlinks make a run directory unsafe; cleanup skips it rather
than deleting through an ambiguous boundary.

## Security boundary

The executor inherits only the existing environment allowlist plus names
explicitly supplied with `--allow-env`. Built-in and optional redaction patterns
are applied before temporary artifacts, diagnostics, or command metadata are
exposed. Secret-shaped argv values, local absolute paths, and oversized argv
items are omitted, normalized, or bounded in the public contract.

Redaction is defense in depth. It is not proof that arbitrary command output is
secret-free, and `pcl exec` is not OS, network, or filesystem isolation.

## When not to use it

Do not wrap commands when their output is the requested artifact, such as:

- `git diff` or `git show`;
- `rg`, `grep`, `cat`, or `sed` used to inspect content;
- reports that the agent must read in full;
- interactive tools, watch mode, servers, or streaming processes.

The cross-agent default rollout is deliberately separate from this runtime.
Global Codex, Claude Code, Gemini CLI, OpenCode, and AGI Cockpit policies should
first adopt explicit `pcl exec` use, measure false classifications, and only then
consider audit-only hooks or narrowly allowlisted rewriting.
