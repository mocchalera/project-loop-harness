---
name: project-control-loop
description: Use this skill when auditing, developing, testing, fixing, or tracking a software project through Project Loop Harness with SQLite memory, evidence-backed status, and a generated HTML dashboard.
---

# Project Control Loop Skill

## Core principle

The dashboard is not the source of truth.
The source of truth is `.project-loop/project.db`, with `.project-loop/events.jsonl` as an append-only audit log.
Generated `dashboard.html` is a human-only review artifact. Agents should not
read or parse it for project state; use `pcl` JSON commands, reports, evidence
paths, or `.project-loop/dashboard/dashboard-data.json` for machine context.

Never edit generated HTML directly.
Never write SQL directly unless the human explicitly asks for database maintenance.
Use the `pcl` CLI for state changes.

## Required behavior

When this skill is invoked:

1. Read `AGENTS.md`, `CLAUDE.md` if present, and `pcl.yaml`.
2. Run `pcl doctor` or `pcl validate` if project-loop state may be stale.
3. Use `pcl next` to determine the next harness action when ambiguous.
4. Perform the smallest valid next step.
5. Record state through `pcl` commands.
6. Run `pcl validate` after state changes.
7. Run `pcl render` after validation.
8. Report evidence, not just conclusions.

`pcl.yaml` `commands.*` values are arbitrary shell commands, not npm script
names or make targets. Run the configured command string exactly as written;
do not assume `npm run <key>` or another wrapper exists for a key like
`lint` or `test`.

## Adoption and setup safety

When initializing or auditing a target project, use the same inspect-first
discipline expected from a careful project setup:

1. Inspect existing `AGENTS.md`, `CLAUDE.md`, `pcl.yaml`, `.agents/`, and
   existing test/build commands before proposing changes.
2. In a non-empty project, prefer `pcl init --dry-run --json` before `pcl init`.
3. Treat the dry-run output as the adoption plan: explain which files would be
   created, updated, skipped, or overwritten.
4. Do not use `pcl init --force` unless the human explicitly approves replacing
   generated templates.
5. After initialization, tune `pcl.yaml` commands, discovery paths, permissions,
   and human gates to the actual repository.
6. Verify the installed harness with `pcl doctor --strict`, `pcl validate
   --strict`, and `pcl render`.

Keep always-loaded files compact. Put procedures in skills, docs, workflow
templates, or reports instead of duplicating long instructions across
`AGENTS.md`, `CLAUDE.md`, and project memory.

## Test-first delivery

Use `pcl story` and `pcl test` as the durable TDD/BDD layer. Free-form testing
docs are useful, but they are not the source of truth once Project Loop Harness
is initialized.

For user-visible behavior changes:

1. Make or identify the feature with `pcl feature add` or `pcl feature read`.
2. Capture behavior as a user story with `pcl story draft`, then review or
   approve it before implementation when feasible.
3. Plan at least one behavior-facing test case with `pcl test plan`.
4. Prefer a red-green-refactor loop: reproduce the missing/failing behavior,
   record `pcl test fail`, `pcl test missing`, or `pcl test block` when useful,
   implement the smallest change, then record `pcl test pass` with evidence.
5. Use explicit evidence: command output, artifact paths, screenshots, commits,
   reports, or verifier notes that another operator can inspect.
6. Run `pcl validate --strict` after terminal test states and before calling the
   loop done.

## Direct implementation loop (default)

For a single well-scoped implementation task, the durable-state path below is
sufficient. Do not start a workflow run just because `pcl next` recommends
one; workflow runs add queued jobs you must later close out.

1. `pcl feature add` (or `pcl feature read` for an existing feature).
2. `pcl story draft` for the behavior.
3. `pcl test plan` for at least one behavior-facing test case.
4. Implement the smallest change.
5. Run project QA commands and collect evidence paths.
6. `pcl test pass TC-XXXX --summary "..." --evidence "..."`.
7. `pcl feature status F-XXXX --status done --evidence "..."`.
8. `pcl validate --strict`.
9. `pcl render`.

Reserve `pcl loop run ...` for coverage sweeps across a goal, defect repair
loops, regression passes, or work that is split across multiple agent jobs.

## Normal commands

```bash
pcl init --dry-run --json
pcl doctor
pcl doctor --strict
pcl validate
pcl validate --strict
pcl next
pcl loop status
pcl update check
pcl render
pcl export csv
```

## State mutation commands

```bash
pcl goal create --title "..."
pcl feature add --name "..." --surface "..." --description "..."
pcl story draft --feature F-0001 --actor "..." --goal "..." --expected-behavior "..."
pcl test plan --feature F-0001 --type acceptance --scenario "..." --expected "..."
pcl test pass TC-0001 --summary "..." --evidence "..."
pcl defect open --feature F-0001 --severity high --expected "..." --actual "..."
```

## Loop commands

Use loop commands to create workflow runs and queued agent jobs:

```bash
pcl loop run feature_coverage --goal G-0001
pcl loop run defect_repair --defect D-0001
pcl loop run regression_loop --goal G-0001
pcl jobs list
pcl jobs read J-0001
```

If you start a workflow run, you own closing it out:

1. Read each queued job with `pcl jobs list` and `pcl jobs read J-XXXX`.
2. Produce each job's output as an agent-output evidence file.
3. Ingest each output with `pcl ingest-agent-run`.
4. Re-run `pcl validate --strict` and `pcl render`.
5. Run `pcl next`. If the remaining action is a human decision — for
   example recording a `pcl verification record` for the workflow run —
   report it as the pending next action and stop. Do not approve or record
   the verification yourself.

## Agent handoff commands

By default, generate prompts and adapter command templates, then ingest the
resulting output as evidence:

```bash
pcl prompt job J-0001
pcl agent command J-0001 --adapter manual
pcl agent command J-0001 --adapter codex_exec
pcl agent command J-0001 --adapter claude_manual
pcl agent command J-0001 --adapter generic_shell
pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md
```

## Guarded executor commands

Workflow command steps are dry-run by default. Execution requires an approved
template and explicit `--execute`:

```bash
pcl workflow verify --template feature_coverage
pcl workflow guard --template feature_coverage
pcl workflow guard --template feature_coverage --execute
```

## Automatic executor commands

Use the guarded executor only when workflow automation is explicitly intended.
Agent adapters launch only with `--allow-agent-exec`:

```bash
pcl loop execute workflow_id
pcl loop execute workflow_id --agent-adapter generic_shell --allow-agent-exec
```

## Human gates

Escalate to the human only when ambiguity changes one of:

- user-visible behavior;
- data handling;
- permissions/security;
- rollout strategy;
- destructive operation;
- external dependency;
- business rule;
- acceptance criteria.

Do not ask questions whose answer can be found in code, tests, docs, `AGENTS.md`, `CLAUDE.md`, or `pcl.yaml`.

When `pcl next` returns an action that requires a human decision, report the
pending action and stop; never satisfy a human gate on the human's behalf.

## Done criteria

A loop is not complete until:

- relevant state is updated through `pcl`;
- evidence exists;
- validation passes;
- dashboard has been regenerated;
- verifier result is recorded or human escalation is opened;
- pending human decisions are reported as such, not self-approved;
- next action is clear.
