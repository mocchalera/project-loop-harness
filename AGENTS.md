# Agent Instructions for Project Loop Harness

This repository implements a reusable local harness for agentic development loops.

## Primary objective

Build a reliable CLI/runtime named `pcl` that can be installed into any software project and can initialize, track, validate, and render a project-scoped agent development loop.

The goal is **not** to create a pretty dashboard first. The dashboard is only a view. The core product is a guarded state machine with durable memory and evidence-backed status transitions.

## Required internal mental model

```text
Goal -> Harness -> Workflow -> Agent Jobs -> Evidence -> Verification -> State -> Dashboard -> Stop/Retry/Escalate
```

This is the maintainer-facing architecture model. Do not assume that a first-time
user or coding agent must learn this entity sequence before receiving value.
GitHub Issue #6 owns the decision about the canonical first-use model and which
internal concepts remain hidden during the first loop.

## Work selection and source of truth

- The human's explicitly assigned GitHub Issue or task identifies the current
  contributor-facing work request.
- Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before starting Issue-backed work.
  GitHub Issues are a projection for discovery and discussion; PCL state,
  accepted repository-local specs, and recorded Evidence remain authoritative.
- Use `scripts/github-issue-map.json` to find the accepted anchors for a mapped
  Issue. Read those anchors before implementation.
- If an assigned Issue has no accepted repository-local anchor, do not invent
  lifecycle status, PCL IDs, or an implementation contract. First create a
  bounded plan/spec and map the Issue to it, then obtain any required human
  decision before implementation.
- `agent-tasks/` is a spec-first backlog and design history. Its numeric order is
  **not** an instruction to execute every file or automatically continue to the
  next number. Work from the explicitly assigned Issue and its accepted anchors.
- Closing or editing a GitHub Issue does not close a PCL target or rewrite
  Evidence. Reconciliation is deliberate and goes through public `pcl` commands
  and committed records.

## Starting assigned work

1. Read the assigned Issue or task, this file, `CONTRIBUTING.md`, and all mapped
   repository-local anchors.
2. Inspect existing PCL state before creating anything. Use `pcl next --json` or
   `pcl resume` when project state exists and the next action is unclear.
3. Attach to an existing matching target when one exists. Do not create a second
   Goal or Task merely because the current agent session is new.
4. Own routine, local, reversible PCL operations and implementation work. Do not
   ask the human to run ordinary PCL commands that the agent is authorized and
   able to run.
5. Run the configured checks, preserve Evidence, and report the factual
   completion state and residual risks. Do not infer success from an exit code,
   artifact existence, or GitHub Issue state alone.
6. Stop for a genuine product decision, permission/security boundary,
   destructive or external action, policy freeze/override, unresolved authority
   ambiguity, or repeated failure without a new safe action.

## Issue #6 bootstrap boundary

GitHub Issue #6, **Zero-to-First-Loop onboarding**, is authorized to begin with
its design-gate/bootstrap phase. Its repository-local starting anchor is
`docs/plan-zero-to-first-loop-onboarding.md`.

Before the canonical first-use decision is accepted:

- inventory and characterize the actual shipped CLI, initialization output,
  documentation, generated instruction blocks, Skills, wheel, and sdist;
- produce one explicit decision proposal for the canonical first-use promise,
  human/agent ownership boundary, GitHub Issue relationship, and stop conditions;
- do not present the full control loop or `pcl verify` as the chosen primary
  entry model before that human decision;
- do not add a new command merely to avoid simplifying an existing path;
- do not rewrite `src/pcl/templates/project/AGENTS.block.md`,
  `src/pcl/templates/project/CLAUDE.block.md`, or bundled agent instructions as
  though the product decision were already settled;
- do not claim external adoption evidence from maintainer dogfood.

After the decision is accepted, split implementation into independently
reviewable task specs before changing runtime behavior or packaged first-use
instructions. This root `AGENTS.md` governs development of PCL; generated
project instruction blocks are product outputs and must be validated separately.

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

<!-- project-loop-harness:start -->
## Project Loop Harness

This repository uses Project Loop Harness.

Rules for coding agents:

- Do not edit `.project-loop/project.db` directly.
- Do not edit `.project-loop/dashboard/dashboard.html` directly.
- Do not read or parse `.project-loop/dashboard/dashboard.html` as project state; it is a human-only view.
- Use `pcl` JSON commands, reports, evidence paths, or `.project-loop/dashboard/dashboard-data.json` for machine context.
- Use `pcl` commands to mutate project-loop state.
- Let project-local instructions, source files, and current system state govern over general guidance.
- Before consequential mutation, identify the accepted outcome, proof boundary, and authority envelope.
- Load only the context and Skills relevant to the current unresolved decision.
- After meaningful state changes, run `pcl validate` and `pcl render`.
- Evidence is required for status changes.
- In non-empty projects, inspect with `pcl init --dry-run --json` before applying initialization changes.
- For behavior changes, capture user stories and test cases with `pcl story` and `pcl test`.
- Human approval is required for database migrations, dependency additions, auth/billing changes, production config changes, and destructive operations.
- Prefer small, verifiable changes.
- Record repeated environment failures with `pcl gap add`; candidate lessons require human promotion approval through `pcl gap promote` and separate application to their durable owner.
- If the same failure repeats, stop and escalate instead of looping indefinitely.
<!-- project-loop-harness:end -->
