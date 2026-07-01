# Data Model

## Tables

The initial schema is in `src/pcl/db/schema.sql`.

Core tables:

- `metadata`
- `schema_migrations`
- `events`
- `goals`
- `workflows`
- `workflow_runs`
- `agent_jobs`
- `features`
- `user_stories`
- `test_cases`
- `defects`
- `decisions`
- `evidence`
- `verifications`
- `escalations`

## Entity relationships

```text
Goal
  └─ WorkflowRun
      ├─ AgentJob
      └─ Verification

Feature
  ├─ UserStory
  ├─ TestCase
  └─ Defect

Defect
  ├─ TestCase?
  ├─ Evidence?
  └─ Verification via WorkflowRun

Decision / Escalation
  └─ blocks Goal, Feature, Defect, or WorkflowRun through JSON references
```

## ID prefixes

| Entity | Prefix | Example |
|---|---|---|
| Goal | G | G-0001 |
| Feature | F | F-0001 |
| User Story | US | US-0001 |
| Test Case | T | T-0001 |
| Defect | D | D-0001 |
| Workflow Run | WR | WR-0001 |
| Agent Job | J | J-0001 |
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
verifications, goals, and defects. Commands must reject invalid jumps instead
of letting agents assign arbitrary status values.

Current implemented examples:

```text
agent_job.queued|running|blocked -> passed|failed|cancelled
workflow_run.queued|running|blocked -> passed|failed|cancelled
goal.open|active|blocked -> closed|cancelled
defect.open -> triaged -> in_progress -> fixed -> verified -> closed
defect.open|triaged|in_progress|fixed|verified -> waived
```

Completing a workflow run requires all jobs to pass and an approved
verification. Closing a goal requires explicit evidence text or an approved
verification. Fixing, closing, or waiving a defect records evidence, and
verifying a defect requires an approved verification tied to the defect repair
workflow run.

## Future improvement

Extend the same transition service to user stories and test cases:

```text
test_case.planned -> passing|failing|blocked|waived
user_story.draft -> review -> approved|waived
```
