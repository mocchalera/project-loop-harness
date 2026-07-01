# Task 0044: Complete CSV Export

## Goal

Expand `pcl export csv` from a small feature/coverage dump into a deterministic review artifact for the full local control loop.

Dogfooding showed that offline review now needs workflow runs, jobs, evidence, verifications, events, human queues, and workflow proposal state in addition to features, stories, tests, defects, goals, and decisions.

## Scope

- Export all reviewable SQLite state tables in a stable order:
  - metadata;
  - schema migrations;
  - events;
  - goals;
  - workflows;
  - workflow runs;
  - agent jobs;
  - features;
  - user stories;
  - test cases;
  - evidence;
  - defects;
  - decisions;
  - verifications;
  - escalations.
- Export workflow proposal review state to `workflow_proposals.csv` from existing proposal files and events.
- Keep the command local-only and dependency-light.
- Write CSV headers even when a table has no rows.
- Keep JSON output predictable as a list of written paths.

## Acceptance criteria

- `pcl export csv --json` writes deterministic CSV files for all exported state.
- Exported `workflow_runs.csv`, `agent_jobs.csv`, `evidence.csv`, `verifications.csv`, and `events.csv` include rows after a representative loop run.
- Exported `decisions.csv` and `escalations.csv` include human queue rows.
- `workflow_proposals.csv` is produced even when no proposals exist.
- Tests cover the expanded export file set and row presence.
- No schema migration is added.

## Do not

- Do not make CSV the source of truth.
- Do not write SQLite directly.
- Do not add external dependencies.
- Do not make export depend on dashboard rendering.
