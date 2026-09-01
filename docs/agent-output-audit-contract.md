# Agent output audit contract

Status: Phase 2a contract candidate for GitHub Issue #13

This document freezes the local observation record that future Claude Code and
Gemini CLI audit-only adapters may emit. It does **not** install a hook, write an
audit file, synchronize a host configuration, or authorize command rewriting.

## Supported protocol identities

The initial contract accepts exactly these documented host tuples:

| Host | Event | Tool |
| --- | --- | --- |
| `claude-code` | `PreToolUse` | `Bash` |
| `gemini-cli` | `BeforeTool` | `run_shell_command` |

These identities are grounded in the current official
[Claude Code hooks reference](https://code.claude.com/docs/en/hooks) and
[Gemini CLI hooks reference](https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/reference.md).
The Gemini shell tool name and input shape are also documented in the official
[shell tool reference](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/shell.md).

The contract does not claim a Codex or OpenCode hook surface. Those hosts remain
instruction-only until a stable documented protocol is separately reviewed and
fixture-bound.

## `agent-output-audit/v1`

A valid observation has this exact shape:

```json
{
  "action": "observed_only",
  "already_wrapped": false,
  "classification": "eligible",
  "command_shape_sha256": "sha256:b354ecfed95e4f4803b87e128b8057e4a3efc526f15c9c446a0a179b6865a600",
  "event": "PreToolUse",
  "host": "claude-code",
  "may_rewrite": false,
  "observed_at": "2026-09-01T00:00:00Z",
  "reason_code": "pytest_direct",
  "schema": "agent-output-audit/v1",
  "tool": "Bash"
}
```

Unknown fields fail closed. The only persisted fields are:

- schema and normalized UTC observation time;
- the exact supported host/event/tool tuple;
- classification, stable reason code, and already-wrapped state;
- fixed `observed_only` action and `may_rewrite: false` authority boundary;
- a category-only command-shape digest.

Reason codes are also a closed v1 allowlist, and each code has exactly one
permitted classification. A future policy extension must update and review the
contract rather than persisting a free-form reason.

## Privacy-reduced command shape

`command_shape_sha256` is **not** a hash of argv, a shell command, tool input,
path, environment, session, or output. It is recomputed from only this bounded
category object:

```json
{
  "schema": "agent-output-command-shape/v1",
  "classification": "eligible",
  "reason_code": "pytest_direct",
  "already_wrapped": false
}
```

The validator rejects a record whose digest does not match those three public
classification fields. This prevents an adapter from hiding raw or
secret-derived input in an opaque hash while still allowing category-level
aggregation.

## Explicitly forbidden data

The record cannot contain command strings, argv, `tool_input`, stdout, stderr,
raw output, current working directory, absolute paths, environment values,
repository URLs, session IDs, transcript paths, or host descriptions. A future
adapter must discard those inputs after classification and must never echo them
in validation errors.

The pure builder accepts a validated `agent-output-classification/v1` result;
it has no parameter for raw command data. It always emits `observed_only` and
`may_rewrite: false`.

## Deferred implementation

The following remain separate slices and human gates:

1. inspect-first host installers and explicit apply/rollback;
2. fixture-bound Claude and Gemini event adapters with unchanged continuation;
3. bounded local audit storage, aggregate report, and retention GC;
4. real host synchronization and cross-host dogfood;
5. any command-rewriting proposal or external rollout.

No hook adapter may deny, ask, allow on behalf of the user, modify tool input,
retry a command, or change an exit result merely because this record contract
exists.
