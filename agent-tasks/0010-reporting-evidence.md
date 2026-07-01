# Task 0010: Reporting Evidence

## Goal

Generate deterministic human-review reports that explain why a goal, workflow run, or defect reached its current status.

The harness already stores state, events, evidence, jobs, and verifications. This task should make that accumulated proof readable without opening SQLite directly.

## Scope

Add CLI/runtime commands for:

- `pcl report goal G-0001`;
- `pcl report run WR-0001`;
- `pcl report defect D-0001`.

Each command should write a Markdown report under `.project-loop/reports/` and return JSON-friendly metadata when `--json` is used.

## Acceptance criteria

- Reports are deterministic for unchanged state.
- Reports include core entity status and summary fields.
- Reports include related events in stable order.
- Reports include related evidence records.
- Run reports include jobs and verifications.
- Goal reports include workflow runs, jobs, verifications, and closure evidence where available.
- Defect reports include feature context, repair workflow runs, verifications, and evidence.
- Dashboard data exposes recent report paths.

## Do not

- Do not edit generated HTML directly.
- Do not write SQLite directly from agents.
- Do not add a schema migration unless reports require durable indexed state.
- Do not include secrets beyond what is already in local project-loop state.
