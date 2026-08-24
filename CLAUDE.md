# Claude Code Project Memory

This project builds **Project Loop Harness**, a CLI/runtime and distribution scaffold for project-scoped agentic development loops.

Claude Code should treat this file as persistent project guidance. Shared work
selection, source-of-truth, and human-gate rules live in `AGENTS.md`; this file
must not define a competing task queue or lifecycle.

## Product in one sentence

`pcl` lets coding agents work inside a governed loop: state in SQLite, audit trail in JSONL, human-readable dashboard in HTML, and repeatable workflows for feature coverage, defect repair, regression, verification, and escalation.

This is a maintainer-facing description of the current architecture, not the
final first-time-user promise. GitHub Issue #6 owns the canonical Zero-to-First-
Loop product decision.

## Non-negotiable architecture

- `pcl` CLI is the core runtime.
- Agent Skills are instruction packages, not the runtime.
- Codex plugins are distribution wrappers, not the runtime.
- MCP is optional and only for external tool access.
- SQLite is the current state store.
- JSONL is the audit trail.
- HTML is generated from state.

## Work selection and Issue #6

- Read `AGENTS.md` before selecting or starting work.
- The human's explicitly assigned GitHub Issue or task is the current
  contributor-facing request. GitHub Issue state is not PCL lifecycle authority.
- Read `CONTRIBUTING.md` and use `scripts/github-issue-map.json` to find accepted
  repository-local anchors.
- `agent-tasks/` is spec history and an accepted implementation backlog, not a
  numeric queue to execute automatically. Read the task spec mapped to the
  assigned work; do not continue to the next number by default.
- For GitHub Issue #6, read `docs/plan-zero-to-first-loop-onboarding.md`. Begin
  with baseline characterization and one product decision proposal only.
  Runtime behavior, generated project instructions, and bundled Skills remain
  blocked until the human decision gate is accepted.

## Implementation behavior

When working on this repo:

1. Read `AGENTS.md`, the assigned Issue/task, `CONTRIBUTING.md`, and all mapped
   anchors.
2. Read `docs/architecture.md` and the relevant accepted plan or
   `agent-tasks/*.md` spec.
3. Inspect existing PCL state before creating a new target; attach to an existing
   matching target when one exists.
4. Implement the smallest safe, authorized slice.
5. Add or update tests.
6. Run `pytest` and any task-specific quality gates.
7. Test `pcl init` against `/tmp/pcl-demo` when initialization behavior changes.
8. Summarize Evidence, factual completion state, and residual risk—not just
   claims.
9. Own routine local PCL commands. Return to the human only for a genuine
   product, permission/security, destructive/external, policy, or unresolved
   authority decision.

## Avoid

- Do not jump to a hosted SaaS version.
- Do not implement autonomous production actions.
- Do not add a complex framework unless it is justified.
- Do not let agents mutate `.project-loop/project.db` with raw SQL.
- Do not let generated dashboard output become the source of truth.
- Do not choose the Issue #6 primary onboarding model before the human decision
  gate.

<!-- project-loop-harness:start -->
## Project Loop Harness

Claude Code should use `pcl` as the only state mutation interface for `.project-loop`.

Before acting:

1. Read `pcl.yaml`.
2. Run `pcl loop status` or `pcl next` when the next action is unclear.
3. Do not read, parse, or hand-edit generated dashboard HTML; it is a human-only view.
4. Use `pcl` JSON commands, reports, evidence paths, or `dashboard-data.json` for machine context.
5. Do not write raw SQL against `.project-loop/project.db`.
6. Let project-local instructions, source files, and current system state govern over general guidance.
7. Before consequential mutation, identify the accepted outcome, proof boundary, and authority envelope.
8. Load only the context and Skills relevant to the current unresolved decision.
9. Use `pcl story` and `pcl test` for behavior-facing test-first work.
10. Preserve evidence paths for claims of completion.
11. Record repeated environment failures with `pcl gap add`; candidate lessons require human promotion approval through `pcl gap promote` and separate application to their durable owner.
<!-- project-loop-harness:end -->
