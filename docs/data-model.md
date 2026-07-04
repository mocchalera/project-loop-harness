# Data Model

## Tables

The database is created and upgraded through ordered SQL migrations in
`src/pcl/db/migrations/`. `src/pcl/db/schema.sql` is the base v1 schema, while
new installs currently apply migrations through schema version 4.

Core tables:

- `metadata`
- `schema_migrations`
- `events`
- `goals`
- `workflows`
- `workflow_runs`
- `agent_jobs`
- `agents`
- `features`
- `user_stories`
- `test_cases`
- `tasks`
- `task_dependencies`
- `defects`
- `decisions`
- `evidence`
- `verifications`
- `escalations`
- `code_index_runs`
- `code_index_files`

## Entity relationships

```text
Goal
  └─ WorkflowRun
      ├─ AgentJob
      └─ Verification

Agent
  └─ AgentJob lease assignment

Feature
  ├─ UserStory
  ├─ TestCase
  └─ Defect

Task
  ├─ Goal?
  ├─ Feature?
  ├─ Defect?
  └─ Task dependencies

Defect
  ├─ TestCase?
  ├─ Evidence?
  └─ Verification via WorkflowRun

Decision / Escalation
  └─ blocks Goal, Feature, Defect, or WorkflowRun through JSON references

CodeIndexRun
  └─ CodeIndexFile
```

## ID prefixes

| Entity | Prefix | Example |
|---|---|---|
| Goal | G | G-0001 |
| Feature | F | F-0001 |
| User Story | US | US-0001 |
| Test Case | TC | TC-0001 |
| Task | T | T-0001 |
| Defect | D | D-0001 |
| Workflow Run | WR | WR-0001 |
| Agent Job | J | J-0001 |
| Agent | A | A-0001 |
| Evidence | E | E-0001 |
| Verification | V | V-0001 |
| Escalation | ESC | ESC-0001 |
| Decision | DEC | DEC-0001 |
| Event | EV | EV-... |

## Status design principles

- Status must be constrained.
- Transitions must append an event.
- Closing a defect must require evidence or waiver.
- Dashboard status is derived, not manually set.

## Lifecycle transitions

The CLI/runtime owns lifecycle transitions for agent jobs, workflow runs,
verifications, goals, defects, stories, test cases, and tasks. Commands must
reject invalid jumps instead of letting agents assign arbitrary status values.

Current implemented examples:

```text
agent_job.queued|running|blocked -> passed|failed|cancelled
workflow_run.queued|running|blocked -> passed|failed|cancelled
goal.open|active|blocked -> closed|cancelled
defect.open -> triaged -> in_progress -> fixed -> verified -> closed
defect.open|triaged|in_progress|fixed|verified -> waived
user_story.draft -> review -> approved|waived
test_case.planned -> passing|failing|blocked|missing|waived
task.todo|ready|in_progress|blocked|done|cancelled|waived -> any other task status with reason
```

## Agent Registry And Leases

Schema version 3 adds an `agents` registry and lease fields on `agent_jobs`.
Agents are durable local records with `name`, `role`, `adapter`,
`max_concurrency`, `status`, and normalized `metadata_json`.

Agent status is constrained to:

```text
agent.active|paused -> active|paused
agent.active|paused -> retired through `pcl agent retire`
```

Agent job status values are unchanged. Lease state is additive:

- `assigned_agent_id` optionally points at `agents.id`.
- `lease_expires_at` records the current lease deadline.
- `last_heartbeat_at` records the latest heartbeat command time.
- `attempts` counts expired lease reaps.

An active lease is a job with `status = 'running'`, `assigned_agent_id` set,
and `lease_expires_at` greater than the current UTC timestamp. Lease expiry is
evaluated lazily by commands; no background process mutates state. The only
command that mutates expired leases is `pcl jobs reap`.

`loop.lease_ttl_seconds` defaults to `1800`. `loop.max_lease_attempts` defaults
to `2` and means total expired lease attempts before blocking: the first expiry
is requeued, and the second expiry blocks the job and opens a high-severity
escalation.

Completing a workflow run requires all jobs to pass and an approved
verification. Closing a goal requires explicit evidence text or an approved
verification. Fixing, closing, or waiving a defect records evidence, and
verifying a defect requires an approved verification tied to the defect repair
workflow run.

## Code Context Index

Schema version 4 adds the approved explainable code context index:

- `code_index_runs`: `id`, `root_path`, `created_at`, `git_head`,
  `file_count`, `indexed_bytes`, `ignored_count`, `index_version`, `status`,
  `summary_json`.
- `code_index_files`: `id`, `index_run_id`, `path`, `language`, `size_bytes`,
  `mtime`, `sha256`, `line_count`, `symbol_summary_json`, `test_hint_json`.

The index is an explicit snapshot. The working tree remains the source of
truth, and status/impact commands report staleness when the snapshot differs
from current file metadata or Git HEAD.

Ignored paths, hash-skip reasons for binary/large files, and language counts
live in `code_index_runs.summary_json`. File-level symbol-lite and test-hint
metadata live in JSON columns on `code_index_files`.

Impact receipts are not a new table. `pcl impact --diff` writes a JSON artifact
under `.project-loop/evidence/context-receipts/` and registers it through the
existing `evidence` table with type `context_receipt`, plus an append-only
event.
