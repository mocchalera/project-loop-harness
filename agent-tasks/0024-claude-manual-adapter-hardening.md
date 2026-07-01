# Task 0024: Claude Manual Adapter Hardening

## Goal

Harden the `claude_manual` adapter instructions so Claude Code handoff is as explicit as manual and Codex adapter handoff.

0021-0023 stabilized the adapter contract, output validation, and Codex command template. Claude manual handoff should now clearly tell an operator what to provide to Claude Code, where to save the response, and how to ingest it.

## Scope

- Keep `pcl agent command J-0001 --adapter claude_manual --json` as instructions only.
- Preserve the existing adapter JSON contract keys.
- Keep `command` as `null`.
- Include `prompt_path`, `output_path`, and `ingest_command` in the instructions.
- Include the `agent-output/v1` requirements:
  - first non-empty line is an H1 summary;
  - `## Findings`;
  - `## Evidence`.
- State that `pcl` does not execute Claude Code automatically.
- Add docs for the Claude manual adapter.
- Add regression tests for actionable instructions and no state mutation on command generation.

## Acceptance criteria

- `claude_manual` command generation does not mutate job status, evidence rows, or events.
- Instructions include prompt path, output path, ingest command, `agent-output/v1`, and required headings.
- Docs describe the Claude manual adapter boundary and flow.
- No Claude Code process is launched in tests.
- No API key management is added.
- No schema migration is added.

## Do not

- Do not call Claude Code from inside `pcl`.
- Do not add dependencies.
- Do not require external credentials in tests.
- Do not make the adapter write SQLite directly.
