# Task 0026: Agent Job Evidence Ingestion

## Goal

Make ingested agent output evidence directly visible from agent job surfaces so Milestone 3 has a complete, inspectable handoff loop:

```text
agent job -> adapter command -> output file -> evidence row -> job/read/list/dashboard/report
```

The ingest command already validates `agent-output/v1`, records `agent_output` evidence, updates the job, and appends `agent_output_ingested`. The remaining gap is that job-centric surfaces should expose the evidence linkage without requiring operators to inspect raw events or SQLite.

## Scope

- Enrich `pcl jobs read J-0001 --json` with:
  - `evidence_ids`;
  - `evidence`;
  - `latest_evidence_id`;
  - `latest_evidence_path`.
- Enrich `pcl jobs list --json` with the same derived evidence fields and `output_path`.
- Derive the linkage from `agent_output_ingested` events and `evidence` rows.
- Preserve append-only event semantics.
- Preserve the existing schema; do not add `agent_jobs.evidence_id`.
- Surface latest job evidence in dashboard data and the agent jobs table.
- Document the job evidence linkage in the adapter contract.
- Add regression tests for ingest -> jobs read/list -> dashboard evidence visibility.

## Acceptance criteria

- Valid `pcl ingest-agent-run` still creates `agent_output` evidence, marks the job passed, appends `agent_output_ingested`, and returns typed JSON.
- `pcl jobs read --json` includes the ingested evidence row and latest evidence fields.
- `pcl jobs list --json` includes `output_path`, evidence ids, and latest evidence fields.
- Dashboard data and HTML include the latest evidence id for ingested jobs.
- Repeated ingests can be represented as multiple evidence ids without schema migration.
- No dependency is added.
- No schema migration is added.

## Do not

- Do not make agents write SQLite directly.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
- Do not edit generated dashboard HTML directly.
- Do not bypass `agent-output/v1` validation.
- Do not add automatic external agent execution.
