# Task 0022: Agent Output Validation

## Goal

Validate external/manual agent output before ingesting it as durable evidence.

0021 stabilized the handoff contract. This task stabilizes the return path so invalid or empty output cannot silently mark an agent job passed.

## Scope

- Add `agent-output/v1` validation to `pcl ingest-agent-run`.
- Reject empty files with typed JSON errors.
- Reject files whose first non-empty line is not a Markdown H1 summary.
- Reject files missing `## Findings` or `## Evidence`.
- Include `contract_version` and validation details in successful ingest JSON output.
- Include validation details in the `agent_output_ingested` event payload.
- Keep the job, evidence table, and events unchanged when validation fails.
- Update the agent output docs and tests to match the runtime contract.

## Acceptance criteria

- Valid output still creates `agent_output` evidence, marks the job passed, appends an event, and appears in reports.
- Invalid output returns a typed JSON error.
- Invalid output does not change job status, evidence rows, or events.
- `pcl ingest-agent-run --json` includes `contract_version` and `validation` on success.
- No external agent is executed automatically.
- No schema migration is added.

## Do not

- Do not add dependencies.
- Do not call Codex, Claude, or any external agent in tests.
- Do not write SQLite directly outside service functions.
- Do not make the output schema complex or model-specific.
