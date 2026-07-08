# Agent Instructions for Project Loop Harness

This repository implements a reusable local harness for agentic development loops.

## Primary objective

Build a reliable CLI/runtime named `pcl` that can be installed into any software project and can initialize, track, validate, and render a project-scoped agent development loop.

The goal is **not** to create a pretty dashboard first. The dashboard is only a view. The core product is a guarded state machine with durable memory and evidence-backed status transitions.

## Required mental model

```text
Goal -> Harness -> Workflow -> Agent Jobs -> Evidence -> Verification -> State -> Dashboard -> Stop/Retry/Escalate
```

## Hard rules

- Do not make agents write SQLite directly.
- Do not make agents edit generated HTML directly.
- All state-changing operations must go through `pcl` commands or internal service functions.
- Every state mutation must append an event.
- Validation must run before rendering whenever possible.
- Generated files must be deterministic.
- Keep the first implementation local-only and dependency-light.
- Prefer simple, explicit, debuggable code over abstractions.

## Implementation style

- Python standard library first.
- Add dependencies only when they remove clear complexity.
- Keep CLI output predictable.
- Use JSON output flags where useful for agents.
- Write tests for every command that mutates state.
- Treat `.project-loop/project.db` as local state.
- Treat `.project-loop/exports/*` and `.project-loop/reports/*` as human-review artifacts.

## Commands agents should run while implementing

```bash
python -m pip install -e '.[dev]'
pytest
pcl --help
```

When working from a linked worktree, do not run `python -m pip install -e ...`
against a shared/global Python environment unless the human explicitly asks for
that environment change. Use `PYTHONPATH=src python -m ...` or a worktree-local
virtual environment so verification uses the worktree source without repointing
the canonical `pcl` entrypoint.

After changing schema or initialization logic:

```bash
rm -rf /tmp/pcl-demo
mkdir /tmp/pcl-demo
pcl init --target /tmp/pcl-demo
pcl doctor --root /tmp/pcl-demo
pcl validate --root /tmp/pcl-demo
pcl render --root /tmp/pcl-demo
```

## Areas where human approval is required

Ask before implementing any of these:

- hosted backend;
- cloud sync;
- production database access;
- automatic GitHub writes;
- dependency on a paid service;
- destructive file operations;
- plugin marketplace publication;
- telemetry collection.

## First task sequence

Use the files in `agent-tasks/` in numeric order. Do not skip directly to MCP or plugin distribution before the CLI and project state layer are solid.

<!-- project-loop-harness:start -->
## Project Loop Harness

This repository uses Project Loop Harness.

Rules for coding agents:

- Do not edit `.project-loop/project.db` directly.
- Do not edit `.project-loop/dashboard/dashboard.html` directly.
- Do not read or parse `.project-loop/dashboard/dashboard.html` as project state; it is a human-only view.
- Use `pcl` JSON commands, reports, evidence paths, or `.project-loop/dashboard/dashboard-data.json` for machine context.
- Use `pcl` commands to mutate project-loop state.
- After meaningful state changes, run `pcl validate` and `pcl render`.
- Evidence is required for status changes.
- In non-empty projects, inspect with `pcl init --dry-run --json` before applying initialization changes.
- For behavior changes, capture user stories and test cases with `pcl story` and `pcl test`.
- Human approval is required for database migrations, dependency additions, auth/billing changes, production config changes, and destructive operations.
- Prefer small, verifiable changes.
- If the same failure repeats, stop and escalate instead of looping indefinitely.
<!-- project-loop-harness:end -->
