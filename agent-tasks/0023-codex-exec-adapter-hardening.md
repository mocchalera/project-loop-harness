# Task 0023: Codex Exec Adapter Hardening

## Goal

Harden the generated `codex_exec` adapter command without making `pcl` execute external agents automatically.

0021 stabilized the adapter command schema and 0022 validates returned output. The Codex CLI adapter should now generate a safer, copy-pasteable command template for non-interactive handoff.

## Scope

- Keep `pcl agent command J-0001 --adapter codex_exec --json` as command generation only.
- Generate a fail-fast shell wrapper with `set -euo pipefail`.
- Create the output directory before invoking Codex.
- Feed the prompt to `codex exec` through stdin instead of command substitution.
- Write the final Codex message through `--output-last-message`.
- Run the generated `pcl ingest-agent-run ... --root ...` command only after Codex succeeds.
- Preserve the existing adapter JSON contract keys.
- Add shell quoting regression tests, including paths with spaces.
- Document the Codex adapter command shape and failure checks.

## Acceptance criteria

- Generated command includes `bash -lc`, `set -euo pipefail`, `codex exec --cd`, `--output-last-message`, stdin prompt redirection, and the ingest command.
- Generated command does not use `$(cat ...)` command substitution for prompt content.
- Generating the command does not mutate job status, evidence rows, or events.
- Tests do not execute Codex CLI.
- No API key management is added.
- No schema migration is added.

## Do not

- Do not call Codex from inside `pcl`.
- Do not add dependencies.
- Do not require OpenAI API keys in tests.
- Do not bypass approvals or sandbox flags automatically.
- Do not make the adapter write SQLite directly.
