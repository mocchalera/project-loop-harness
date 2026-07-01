# Claude Code Project Memory

This project builds **Project Loop Harness**, a CLI/runtime and distribution scaffold for project-scoped agentic development loops.

Claude Code should treat this file as persistent project guidance.

## Product in one sentence

`pcl` lets coding agents work inside a governed loop: state in SQLite, audit trail in JSONL, human-readable dashboard in HTML, and repeatable workflows for feature coverage, defect repair, regression, verification, and escalation.

## Non-negotiable architecture

- `pcl` CLI is the core runtime.
- Agent Skills are instruction packages, not the runtime.
- Codex plugins are distribution wrappers, not the runtime.
- MCP is optional and only for external tool access.
- SQLite is the current state store.
- JSONL is the audit trail.
- HTML is generated from state.

## Implementation behavior

When working on this repo:

1. Read `docs/architecture.md` first.
2. Read the relevant `agent-tasks/*.md` file.
3. Implement the smallest safe slice.
4. Add or update tests.
5. Run `pytest`.
6. Test `pcl init` against `/tmp/pcl-demo`.
7. Summarize evidence, not just claims.

## Avoid

- Do not jump to a hosted SaaS version.
- Do not implement autonomous production actions.
- Do not add a complex framework unless it is justified.
- Do not let agents mutate `.project-loop/project.db` with raw SQL.
- Do not let generated dashboard output become the source of truth.

<!-- project-loop-harness:start -->
## Project Loop Harness

Claude Code should use `pcl` as the only state mutation interface for `.project-loop`.

Before acting:

1. Read `pcl.yaml`.
2. Run `pcl loop status` or `pcl next` when the next action is unclear.
3. Do not hand-edit generated dashboard HTML.
4. Do not write raw SQL against `.project-loop/project.db`.
5. Preserve evidence paths for claims of completion.
<!-- project-loop-harness:end -->
