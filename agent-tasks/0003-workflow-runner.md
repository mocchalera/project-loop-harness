# Task 0003: Implement Workflow Runner Skeleton

## Goal

Make `pcl loop run <workflow_id>` create a workflow run and agent job records from a YAML workflow template.

## Read first

- `docs/workflow-contract.md`
- `src/pcl/templates/workflows/*.yaml`
- `docs/agent-roles.md`

## Scope

Implement:

- minimal YAML parser strategy;
- if dependency-free parsing is too brittle, propose adding `PyYAML` with justification;
- workflow loading from `.project-loop/workflows/`;
- `workflow_runs` insertion;
- `agent_jobs` insertion;
- prompt file generation under `.project-loop/evidence/agent-runs/<job_id>/prompt.md`;
- `pcl jobs list`;
- `pcl jobs read <job_id>`;
- no automatic model invocation yet.

## Acceptance criteria

```bash
pcl loop run feature_coverage --goal G-0001
pcl loop status
pcl jobs list
```

A workflow run and expected jobs should exist in SQLite and be visible in dashboard after render.

## Do not

- Do not call Codex or Claude directly in this task.
- Do not execute arbitrary commands from YAML yet.
