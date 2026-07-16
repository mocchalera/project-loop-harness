# Adoption Guide

This guide is for taking Project Loop Harness from this repository into a new
software project.

## Safe coexistence with an existing project

Adoption is inspect-first and additive. In a non-empty repository, start with:

```bash
pcl init --dry-run --json
```

The plan reports which files would be created, updated, or skipped. Normal
initialization preserves existing project instructions and configuration:

- existing `AGENTS.md`, `CLAUDE.md`, and `.gitignore` content is retained;
- the Project Loop instruction block is added once and is not duplicated on a
  rerun;
- an existing `pcl.yaml` is preserved;
- `.project-loop/project.db` remains local state rather than a file agents edit;
- generated dashboard HTML is a human view, not machine context.

Do not use `pcl init --force` merely to adopt an existing repository. `--force`
is an explicit replacement boundary for generated templates and requires a
human decision after reviewing the dry-run plan.

After this one-time setup, humans should be able to state an outcome in their
agent interface while the agent runs routine `pcl` commands. Human involvement
is reserved for real decisions such as permissions, migrations, destructive
operations, product behavior, and external services.

Use it when you need to answer three operator questions:

- how to distribute the `pcl` runtime;
- how to initialize a target project safely;
- what to ask the first coding agent to do.

## Distribution Options

Project Loop Harness has multiple pieces, but the runtime is always the Python
package that provides `pcl`.

```text
pcl CLI      = runtime and state machine
Skill        = agent instructions installed by `pcl init`
Plugin       = Codex packaging wrapper
MCP server   = optional local bridge
GitHub Action = optional validation wrapper
```

### Current Practical Default: PyPI Install

For normal operator use, install the published package from PyPI with `pipx`:

```bash
pipx install project-loop-harness
pcl --version
pcl --help
```

`uv` users can install the same isolated CLI with:

```bash
uv tool install project-loop-harness
pcl --version
```

To check for updates later, run:

```bash
pcl update check
pcl update command
```

`pcl update check` reads PyPI metadata only when explicitly requested, caches the
latest version for 24 hours, and does not upgrade the environment. The companion
`pcl update command` prints the manual upgrade command for the detected install
shape, such as `pipx upgrade project-loop-harness` for pipx installs.

Use `python -m pip install project-loop-harness` when installing inside a
project-specific virtual environment or CI job instead of exposing the command
globally.

### Pinned Git Install

For unreleased commits or internal dogfooding, install from GitHub over HTTPS
and pin a commit or tag for team use:

```bash
python -m pip install "project-loop-harness @ git+https://github.com/mocchalera/project-loop-harness.git@<commit-or-tag>"
pcl --help
```

For an isolated command install, `pipx` can install the same Git package:

```bash
pipx install "git+https://github.com/mocchalera/project-loop-harness.git@<commit-or-tag>"
pcl --help
```

Use `main` only for local dogfooding. For another project or another operator,
prefer the PyPI package, a tag, or a full commit hash so the initialized
project can be reproduced.

### Local Wheel Handoff

When you want to test the exact distribution artifact before sharing it:

```bash
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/pcl-wheelhouse
python -m venv /tmp/pcl-wheel-venv
/tmp/pcl-wheel-venv/bin/python -m pip install --no-deps /tmp/pcl-wheelhouse/project_loop_harness-*.whl
/tmp/pcl-wheel-venv/bin/pcl --help
/tmp/pcl-wheel-venv/bin/pcl-mcp --help
```

Then initialize a scratch project with the wheel-installed binary:

```bash
/tmp/pcl-wheel-venv/bin/pcl init --target /tmp/pcl-dist-demo
/tmp/pcl-wheel-venv/bin/pcl validate --root /tmp/pcl-dist-demo --strict
/tmp/pcl-wheel-venv/bin/pcl render --root /tmp/pcl-dist-demo --json
```

### Optional Wrappers

These are useful after the CLI is already installed and understood:

- Codex plugin scaffold: `plugins/codex-project-loop/`
- local MCP server: `pcl-mcp --stdio --root <project>`
- GitHub Action: `.github/actions/project-loop-validate/action.yml`

The wrappers do not replace the runtime. State mutations still go through
`pcl`.

## New Project Start

Run these steps from the target project root.

### 1. Install The Runtime

Use one of the distribution options above, then verify:

```bash
pcl --help
pcl-mcp --help
```

### 2. Initialize The Project

```bash
cd /path/to/target-project
pcl init --dry-run --json
pcl init
pcl doctor
pcl validate --strict
pcl render --json
```

`pcl init` adds local state, workflow templates, agent instructions, and
operator guidance. It is safe to rerun; existing `AGENTS.md`, `CLAUDE.md`, and
`.gitignore` blocks are not duplicated.

Use the dry-run output as the inspect-first adoption plan for non-empty
projects. It lists the files and directories that would be created, updated,
skipped, or overwritten without touching local state. Only use `pcl init
--force` after a human has reviewed and approved template replacement.

### 3. Confirm `pcl.yaml`

For common Node and Python repositories, `pcl init` detects the project name and
safe verification commands. Detection reads configuration as data; it never
executes `package.json`, `pyproject.toml`, `setup.py`, or project commands.
Unknown commands are written as `null` so they are explicitly disabled rather
than ambiguous empty placeholders.

Run:

```bash
pcl doctor --strict
```

Only edit `pcl.yaml` where the detected plan is incomplete or wrong:

- set `project.name` and `project.type`;
- fill `commands.install`, `commands.lint`, `commands.test`, and other known
  checks;
- make `discovery.include` match real source and test directories;
- keep secrets, migrations, generated state, and production config out of
  `permissions.agent_may_modify`;
- add human approval gates for migrations, dependencies, auth, production
  config, destructive operations, and external writes.
- set `dashboard.locale: "ja"` when the operator wants Japanese HTML chrome;
  the default remains English and `pcl render --locale ...` overrides it for a
  single render.

Then rerun health checks:

```bash
pcl validate --strict
pcl render --json
```

### 4. Decide What To Commit

Commit the project policy and reusable instructions:

```text
pcl.yaml
AGENTS.md
CLAUDE.md
.agents/skills/project-control-loop/SKILL.md
.project-loop/workflows/*.yaml
.gitignore
```

Keep local state out of normal commits:

```text
.project-loop/project.db
.project-loop/project.db-*
.project-loop/events.jsonl
.project-loop/evidence/
.project-loop/worktrees/
.project-loop/tmp/
.project-loop/cache/
```

The generated review artifacts may be committed only if the team wants them in
the repository:

```text
.project-loop/dashboard/
.project-loop/reports/
.project-loop/exports/
```

### 5. Run The First Loop

For a new project, start with a bounded goal:

```bash
pcl goal create --title "Reach basic feature coverage"
pcl loop run feature_coverage --goal G-0001
pcl next --json
```

Then follow `pcl next`. It is the router for validation failures, human queues,
active workflows, defects, goals, and feature coverage.

The installed Project Control Loop Skill distinguishes routine rendering from
operator presentation. The agent presents the dashboard after plan approval,
at a major milestone, when human input blocks progress, and after goal closure.
It should open the generated file in a host-provided visual/file panel when one
exists, or provide the path otherwise, and state what to inspect using **Now,
Done, Next, Human needed, and Risks**. It should not interrupt the operator with
the dashboard after every state mutation.

The first dashboard section is the simple operator view. Detailed counters,
commands, queues, Evidence, and entity tables remain available under the native
HTML disclosure labeled **Detailed Project Loop information**. Dashboard HTML
is still a human-only view; agents prepare their explanation from `pcl` JSON
state rather than parsing the page.

After several small features, use the checkpoint reminder to review the larger
product direction without stopping normal work by default:

```bash
pcl checkpoint status --json
pcl checkpoint record \
  --review-type ux \
  --summary "Reviewed checkpoint before more feature coverage" \
  --evidence "Reviewed dirty worktree, validation output, UX checklist, and next high-impact feature"
```

Use this checkpoint to decide commit/package boundaries, refresh any hands-on UX
checklist, and choose the next feature by contribution to the larger product
goal rather than simply taking the next small item.

The generated configuration defaults to `checkpoint.mode: advisory`, so
`pcl next` continues normal Task and Goal routing while the dashboard shows the
reminder under risks/attention. Set the mode to `blocking` only for projects
that intentionally require a human checkpoint at the configured
`feature_interval`, or set it to `off` to disable cadence reminders.

For test-first work, keep behavior in harness state instead of only in prose:

```bash
pcl feature add --name "Import invoices" --surface "cli:import" --task T-0001
pcl story draft --feature F-0001 --actor "operator" --goal "import invoices" --expected-behavior "valid CSV rows become invoice records"
pcl story approve US-0001 --summary "Acceptance behavior is clear"
pcl test plan --feature F-0001 --story US-0001 --type acceptance --scenario "Valid CSV import" --expected "Invoices are created and reported"
```

Then run the relevant project command, record the red/green result with `pcl
test fail`, `pcl test missing`, `pcl test block`, or `pcl test pass`, and use
`pcl validate --strict` before calling the loop done.

`--task` links the new Feature to an existing unlinked Task atomically. If the
Task is unknown or already linked, no Feature is created. When terminal Task,
Feature, and Test work is already complete, `pcl next` recommends
`pcl finish --emit-packet` directly (or finish-check configuration first)
instead of starting redundant `feature_coverage` work.

For a command-only smoke check of the executor:

```bash
pcl workflow verify --template executor_smoke
pcl workflow guard --template executor_smoke --json
pcl loop execute executor_smoke --json
pcl validate --strict
```

## First Agent Prompts

The first prompt should make the harness boundary explicit. Do not ask the
agent to "manage project state" in prose. Ask it to use `pcl`.

### Orientation Prompt

Use this when the target project has just been initialized and you want the
agent to inspect without making product changes:

```text
Read AGENTS.md, CLAUDE.md if present, README.md, and pcl.yaml.

This project uses Project Loop Harness. Do not edit `.project-loop/project.db`,
`.project-loop/events.jsonl`, or generated dashboard HTML directly. Do not
read or parse generated dashboard HTML as project state. Use `pcl` commands for
loop state changes and `pcl` JSON, reports, evidence paths, or
`dashboard-data.json` for machine context.

Run:
- pcl validate --json
- pcl validate --strict --json
- pcl next --json

Then tell me:
- whether the harness is healthy;
- what `pcl next` recommends;
- what first bounded goal you recommend for this repository;
- any project-specific changes needed in `pcl.yaml`.

Do not implement code changes yet.
```

### Start-Work Prompt

Use this when you are ready for the agent to begin the first loop:

```text
Use Project Loop Harness for this work.

First run `pcl next --strict --json`. If it reports validation errors, fix the
smallest safe issue first. If it recommends creating or continuing a goal,
follow the recommended `pcl` command.

All loop state mutations must go through `pcl`. Do not edit SQLite, events
JSONL, or generated dashboard HTML directly. Do not read or parse generated
dashboard HTML as project state.

Keep the first goal bounded. Prefer `feature_coverage`, `defect_repair`, or the
bundled `executor_smoke` workflow before proposing new workflow templates.
For behavior changes, use `pcl story` and `pcl test` to capture acceptance
behavior before or alongside implementation.

After meaningful state changes, run:
- pcl validate --strict --json
- pcl render --json

Report the commands run, generated evidence or report paths, and the final
`pcl next --json` action.
```

When reading `pcl next --json`, treat `safe_to_run: false` as "do not auto-run
blindly", not as "this command is forbidden." If `requires_human: true`, a
person should choose, verify, or confirm the transition before it is recorded.

### Implementation Prompt

Use this once a goal or workflow already exists:

```text
Continue the current Project Loop Harness workflow.

Run `pcl next --strict --json` and take the next safe action. Use `pcl jobs
read`, `pcl prompt job`, or `pcl agent command` for agent jobs. If a human
decision is required, open or resolve escalation/decision state with `pcl`
instead of leaving it as free text.

Implement only the smallest scoped change needed for the current goal. Add or
update tests for mutating behavior. Preserve unrelated user changes.

Before finishing, run the relevant tests plus:
- pcl validate --strict --json
- pcl render --json

Summarize evidence, not just conclusions.
```

### Target-Bound Code Context Handoff

When you hand another agent code context for a specific task or job, bind the
receipt to that target and require the binding, so the worker cannot receive an
unrelated receipt under a target-bound label:

```text
pcl index build --json
pcl impact --diff --for-task T-0001 --json
pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json
```

Use the `--for-job` / `--job` forms for agent-job handoffs. `--require-bound-receipt`
turns a missing target binding into a typed failure
(`context_pack_bound_receipt_required`) instead of a silent unscoped fallback.
This presumes a diff already exists for the target; it is a review/continuation
handoff, not a pre-implementation context primitive.

## Operator Checklist

Before handing a target project to another agent, confirm:

- `pcl --help` works in that environment;
- `pcl init --dry-run --json` was reviewed for a non-empty project;
- `pcl init` has been run;
- `pcl.yaml` has real project commands and permissions;
- `pcl validate --strict` passes;
- `pcl render --json` returns dashboard artifact paths for human review and machine JSON;
- for target-scoped code handoffs, `pcl context pack --include-code-context --require-bound-receipt` against the intended task or job succeeds (a bound receipt exists);
- the committed files exclude local DB, JSONL audit log, and evidence blobs
  unless the team intentionally chose otherwise;
- the first prompt tells agents to use `pcl` or dashboard-data JSON, not raw SQLite or generated HTML.
