# Task 0025: Generic Shell Adapter

## Goal

Add a vendor-neutral shell adapter command so any operator-provided local agent command can consume a queued job prompt and return `agent-output/v1` evidence without adding automatic execution to `pcl`.

Codex and Claude handoffs are now explicit. The next adapter should make the external-agent boundary usable for local tools that read from stdin and write Markdown to stdout.

## Scope

- Add `pcl agent command J-0001 --adapter generic_shell --json`.
- Preserve the existing adapter JSON contract keys.
- Return a copy-pasteable `bash -lc` wrapper in `command`.
- Require operators to set `PCL_AGENT_COMMAND` to a shell command that:
  - reads the prompt from stdin;
  - writes an `agent-output/v1` Markdown report to stdout.
- The wrapper should:
  - use `set -euo pipefail`;
  - create the output directory;
  - pass the job prompt to `PCL_AGENT_COMMAND` through stdin;
  - write stdout to `.project-loop/evidence/agent-runs/<job_id>/output.md`;
  - require the output file to be non-empty before ingest;
  - run `pcl ingest-agent-run ... --root ...` only after the shell command succeeds.
- Include `prompt_path`, `output_path`, `ingest_command`, and output format requirements in instructions.
- Add docs for the generic shell adapter.
- Add regression tests for command shape, no state mutation, and the handoff/ingest happy path.

## Acceptance criteria

- `generic_shell` exposes the same JSON keys as `manual`, `codex_exec`, and `claude_manual`.
- The generated wrapper contains `bash -lc`, `set -euo pipefail`, `PCL_AGENT_COMMAND`, stdin prompt redirection, stdout output redirection, non-empty output check, and the ingest command.
- Generating the command does not mutate job status, evidence rows, or events.
- The `jobs read` / `prompt job` / `agent command` / `ingest-agent-run` happy path records evidence and reports it.
- Docs describe the adapter boundary and output contract.
- Tests do not execute arbitrary external agents.
- No dependency is added.
- No schema migration is added.

## Do not

- Do not execute the generated shell command from inside `pcl`.
- Do not add hosted services or external credentials.
- Do not make adapters write SQLite directly.
- Do not ingest output before `agent-output/v1` validation.
- Do not edit generated dashboard HTML directly.
