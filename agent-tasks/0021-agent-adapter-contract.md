# Task 0021: Agent Adapter Contract

## Goal

Stabilize the contract between `pcl` agent jobs and external/manual agent execution.

The harness already creates agent jobs, writes prompts, generates adapter command templates, and ingests output as evidence. The next step is to make that boundary explicit enough that humans, Codex CLI, Claude Code, or another adapter can hand work off without guessing paths or output expectations.

## Scope

- Document `pcl jobs read`, `pcl prompt job`, `pcl agent command`, and `pcl ingest-agent-run`.
- Define the JSON contract for `pcl agent command J-0001 --adapter manual|codex_exec|claude_manual --json`.
- Ensure every adapter response includes:
  - contract version;
  - adapter name;
  - job id;
  - prompt path;
  - expected output path;
  - ingest command;
  - expected output format;
  - optional executable command.
- Add a minimal agent output example under `docs/`.
- Add tests for the full happy path:
  - create workflow and job;
  - read job prompt;
  - generate adapter command;
  - write output file to expected path;
  - ingest output;
  - verify evidence/event/job/report reflection.

## Acceptance criteria

- `manual`, `codex_exec`, and `claude_manual` expose the same JSON keys.
- Adapter command output always points to `.project-loop/evidence/agent-runs/<job_id>/output.md`.
- Adapter command output always includes the ingest command that records the output as evidence.
- `pcl ingest-agent-run` remains the only state mutation for external agent output.
- Reports include ingested agent output evidence and `agent_output_ingested` events.
- No external agent is executed automatically.
- No schema migration is added.

## Do not

- Do not add hosted services.
- Do not require API keys.
- Do not shell out to Codex or Claude during tests.
- Do not let adapters write SQLite directly.
- Do not add package dependencies.
