# 0141: Idle routing without a redundant human gate

- **Status:** Approved implementation slice
- **Milestone:** v0.4.1 Integrity Migration
- **Priority:** P0
- **Estimated size:** S
- **Dependencies:** 0136 (`pcl start`), 0140a–0140c (v0.4.0 Integrity Gate)

## Problem

When a project has no active work, `pcl next` currently recommends a fixed
`Reach feature coverage` Goal and marks that recommendation as a human
decision. If a user has already supplied a literal implementation intent, this
creates a meaningless confirmation round trip. The v0.4.0 `pcl start`
command is already the guarded entry point for registering that intent.

## Goal

Represent a genuinely idle project as neutral read-only state, without
inventing a durable mutation or human approval. Teach agents to pass an
explicit user intent literally to `pcl start`.

## Contract

When no active Goal, Task, Defect, Workflow, Decision, Escalation, checkpoint,
or uncovered Feature action exists, `pcl next --json` returns the ordinary
guided-action keys with:

- `type: "idle"`;
- `command: null`;
- `target: null`;
- `blocking: false`;
- `requires_human: false`;
- `safe_to_run: false` because there is no command to execute;
- `run_policy: "idle"`;
- factual guidance to call `pcl start "<intent>"` only when explicit intent is
  available.

The `command` field remains a string for executable and human-gated actions.
Its nullability is limited to action shapes that intentionally have no command.

## Scope

- Replace the terminal fixed-Goal fallback in `src/pcl/commands.py`.
- Keep `pcl next --explain`, dashboard data, dashboard HTML, MCP output, and
  distribution smoke behavior coherent with the nullable idle command.
- Update the three byte-identical `project-control-loop` Skill copies.
- Update direct tests and the generated baseline snapshot with an intentional
  contract-drift note.

## Invariants

- `pcl next` remains read-only.
- Real human gates retain their existing priority and fields.
- Existing active-work, defect, task, workflow, checkpoint, and uncovered
  Feature routing is unchanged.
- `pcl start` continues to treat intent as literal text and preserves its
  duplicate-active-work guard.
- No schema migration, dependency, LLM call, agent launch, or remote operation.

## Acceptance criteria

- A freshly initialized empty project returns the idle contract above.
- `pcl next --explain` does not print `None` as an executable command.
- An open Decision still returns the existing human-gated action before idle.
- Example and fresh-wheel distribution tests expect the idle contract.
- The current baseline snapshot is regenerated and its intentional delta is
  documented.
- The canonical Skill copies remain byte-identical.
- Targeted tests, full `pytest`, `ruff check .`, strict validation, and render
  pass.
