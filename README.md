# Project Loop Harness

Project Loop Harness is a local control plane for coding agents.

It is not just an Agent Skill. The core product is `pcl`, a small local CLI/runtime that gives Codex, Claude Code, and similar agents a guarded project-scoped loop: durable state in SQLite, append-only audit events in JSONL, generated prompts and evidence, strict validation, human-readable reports, and a deterministic dashboard.

## Quick Start

Install the published `pcl` CLI/runtime from PyPI with `pipx`:

```bash
pipx install project-loop-harness
pcl --version
pcl --help
```

Use `python -m pip install project-loop-harness` when installing inside a
project-specific virtual environment or CI job instead of exposing the command
globally.

For unreleased changes, install from a pinned GitHub tag or commit:

```bash
pipx install "git+https://github.com/mocchalera/project-loop-harness.git@<commit-or-tag>"
```

Initialize a target project:

```bash
cd target-project
pcl init
pcl doctor
pcl validate --strict
pcl render --json
```

Then ask your coding agent to read `AGENTS.md`, `CLAUDE.md` if present, and
`pcl.yaml`, run `pcl next --json`, and follow the next safe harness action.

## Mental Model

```text
Goal -> Harness -> Workflow -> Agent Jobs -> Evidence -> Verification -> State -> Dashboard -> Stop/Retry/Escalate
```

The important separation is:

```text
Skill          = instructions for agents
pcl CLI        = runtime that mutates state, validates, renders, and routes work
project.db     = current normalized loop memory
events.jsonl   = append-only audit log
dashboard.html = generated human-readable view
Plugin         = Codex distribution wrapper
MCP            = optional read/local-render bridge
```

Agents should never edit `.project-loop/project.db` or generated dashboard HTML directly. State changes go through `pcl` commands or internal service functions, and every state mutation appends an event.

## Repository Layout

```text
project-loop-harness/
|- src/pcl/                         # Python CLI/runtime
|- skills/project-control-loop/      # Standalone Agent Skill template
|- plugins/codex-project-loop/       # Codex plugin packaging scaffold and inventory
|- docs/                            # Architecture and operational docs
|- agent-tasks/                     # Numbered implementation tasks
|- examples/                        # Example project configs
`- tests/                           # CLI/runtime tests
```

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
pcl --help
```

## Distribution Smoke Test

Before releasing a new version or handing the runtime to another project,
verify a wheel install rather than only editable install:

```bash
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/pcl-wheelhouse
python -m venv /tmp/pcl-wheel-venv
/tmp/pcl-wheel-venv/bin/python -m pip install --no-deps /tmp/pcl-wheelhouse/project_loop_harness-*.whl
/tmp/pcl-wheel-venv/bin/pcl --help
/tmp/pcl-wheel-venv/bin/pcl-mcp --help
```

The automated version is covered by:

```bash
pytest tests/test_distribution.py
```

## Adoption Guide

For practical rollout into another repository, use
[docs/adoption-guide.md](docs/adoption-guide.md). It covers target-project
setup, optional Git and local wheel handoff paths, what `pcl init` adds to a
target project, which files to commit, and starter prompts for the first agent
session.

## Golden Path

This path runs a complete feature-coverage loop in a temporary project:

```bash
rm -rf /tmp/pcl-demo
mkdir -p /tmp/pcl-demo

pcl init --target /tmp/pcl-demo
pcl doctor --root /tmp/pcl-demo

pcl goal create --root /tmp/pcl-demo --title "Reach basic feature coverage"
pcl loop run --root /tmp/pcl-demo feature_coverage --goal G-0001

pcl next --root /tmp/pcl-demo --json
pcl jobs read --root /tmp/pcl-demo J-0001
pcl jobs complete --root /tmp/pcl-demo J-0001 --summary "Mapped project surfaces"
pcl jobs complete --root /tmp/pcl-demo J-0002 --summary "Wrote user stories"
pcl jobs complete --root /tmp/pcl-demo J-0003 --summary "Designed test cases"

pcl next --root /tmp/pcl-demo --explain
pcl verification record --root /tmp/pcl-demo --run WR-0001 --result approved --reason "Reviewed generated coverage"
pcl loop complete --root /tmp/pcl-demo WR-0001 --summary "Feature coverage complete"
pcl goal close --root /tmp/pcl-demo G-0001 --summary "Coverage goal done" --verification V-0001

pcl validate --root /tmp/pcl-demo --strict
pcl report goal --root /tmp/pcl-demo G-0001
pcl report run --root /tmp/pcl-demo WR-0001
pcl feature list --root /tmp/pcl-demo --json
pcl render --root /tmp/pcl-demo
```

Open `/tmp/pcl-demo/.project-loop/dashboard/dashboard.html` after rendering.

See [docs/golden-path.md](docs/golden-path.md) for the same path with expected checkpoints and a human-decision branch.

For approved workflows that pass the executor preflight, the guarded automatic
path is:

```bash
pcl workflow verify --root /tmp/pcl-demo --template executor_smoke
pcl workflow sandbox --root /tmp/pcl-demo --template executor_smoke --json
pcl loop execute --root /tmp/pcl-demo executor_smoke --json
```

Failed or interrupted executor runs are recovered explicitly:

```bash
pcl loop execute workflow_id --retry WR-0001
pcl loop execute workflow_id --resume WR-0001
```

Agent steps are not launched unless explicitly enabled:

```bash
pcl loop execute workflow_id --agent-adapter generic_shell --allow-agent-exec
```

## Guided Next Actions

`pcl next` is the loop router. The JSON output keeps the original fields and adds stable guidance fields:

```json
{
  "type": "continue_workflow",
  "command": "pcl jobs read J-0001",
  "reason": "A workflow run is already active and has queued or running jobs.",
  "target": {"id": "WR-0001"},
  "priority": 40,
  "blocking": false,
  "requires_human": false,
  "safe_to_run": true,
  "run_policy": "agent_safe",
  "human_guidance": "An agent or automation may run this command in the current project context.",
  "expected_after": "The agent job prompt is reviewed and the job can be executed or completed."
}
```

Use:

```bash
pcl next --json
pcl next --explain
pcl next --strict --json
```

Priority order is fixed:

1. strict validation failure
2. open escalation
3. open decision
4. `needs_human` verification requiring escalation
5. active workflow lifecycle
6. executor retry routing
7. open defect lifecycle
8. workflow proposal review
9. checkpoint review after several done features
10. open goal continuation
11. uncovered feature coverage
12. create goal

## Checkpoint Reviews

Dogfooding showed that Project Loop is effective at small verified improvements,
but large UX goals still need periodic human prioritization. Use checkpoint
reviews to pause after several done features, organize commit/package boundaries,
refresh UX or interaction checklists, and choose the next feature by product
impact:

```bash
pcl checkpoint status --json
pcl checkpoint record \
  --review-type integration \
  --summary "Reviewed commit boundary, UX checklist, and next priority" \
  --evidence "Reviewed validation output, git diff, UX checklist, and next feature priority"
```

When five features are marked `done` after the latest checkpoint, `pcl next`
returns `checkpoint_review` before recommending another feature-coverage run.

## Human Decision Flow

When verification needs human judgment, keep ambiguity and the decision as durable state:

```bash
pcl verification record --root /tmp/pcl-demo --run WR-0001 --result needs_human --reason "Product decision required"
pcl next --root /tmp/pcl-demo --json

pcl escalation open --root /tmp/pcl-demo --run WR-0001 --severity high --question "What should ship?" --recommendation "Choose the safest reversible path"
pcl decision open --root /tmp/pcl-demo --escalation ESC-0001 --question "Which path should we take?" --recommendation "Choose the safest reversible path"
pcl decision resolve --root /tmp/pcl-demo DEC-0001 --selected-option "Ship locally first" --reason "Risk stays local"
pcl escalation resolve --root /tmp/pcl-demo ESC-0001 --decision DEC-0001 --summary "Human decision recorded"
```

Escalations and decisions are linked through `decisions.blocks_json` and event payloads. Dashboard rows and reports show `linked_escalation_ids` and `linked_decision_ids`.

## Reports And Dashboard

Generated artifacts are review surfaces, not sources of truth:

```bash
pcl report goal --root /tmp/pcl-demo G-0001
pcl report run --root /tmp/pcl-demo WR-0001
pcl report feature --root /tmp/pcl-demo F-0001
pcl report defect --root /tmp/pcl-demo D-0001
pcl report validation --root /tmp/pcl-demo --strict
pcl render --root /tmp/pcl-demo
```

Reports are written to `.project-loop/reports/`. The dashboard writes:

```text
.project-loop/dashboard/dashboard-data.json
.project-loop/dashboard/dashboard.html
```

Run `pcl validate` before rendering whenever possible. `pcl render` already performs normal validation and refuses to render on errors.

If validation fails or generated artifacts look stale, use [docs/recovery-playbook.md](docs/recovery-playbook.md) before continuing normal work.

## Example Projects

Seed configs live under [examples/](examples/). Copy one to a scratch directory, run `pcl init --target ...`, then follow the golden path without committing generated `.project-loop/` state back into the example.

## Current Runtime Surface

The current local runtime supports:

- `pcl init`, `doctor`, `validate`, `migrate`, migration status, `render`;
- feature creation, inspection, and evidence-backed status changes;
- workflow run creation from static templates;
- agent job prompts, filtered inspection, adapter commands, completion/failure/cancellation;
- documented agent adapter command contract;
- hardened Codex CLI adapter command template;
- hardened Claude Code manual adapter instructions;
- generic shell adapter command template;
- validated agent output ingestion as evidence;
- job-centric evidence linkage for ingested agent output;
- verification recording;
- workflow run, goal, defect, escalation, and decision lifecycle commands;
- escalation/decision linkage;
- checkpoint review commands for commit/package, UX checklist, and next-priority pauses;
- strict validation invariants and audit-log integrity checks;
- evidence-backed Markdown reports;
- deterministic dashboard data and HTML with JSON artifact paths, a versioned data contract, evidence navigation, and risk/blocker summary;
- guided `pcl next` actions with uncovered-feature routing;
- complete CSV export for reviewable loop state;
- optional local stdio MCP server;
- Codex plugin packaging scaffold with package inventory and reusable GitHub Action for local validation;
- workflow proposal mode, guarded human approval, static verifier checks, limited sandbox planning/execution, guarded automatic workflow execution with explicit retry/resume, and a bundled `executor_smoke` workflow for dogfooding the executor.

## Implementation Task Order

Give tasks to coding agents in numeric order:

```text
agent-tasks/0001-hardening-cli.md
...
agent-tasks/0017-next-action-guided-loop.md
agent-tasks/0018-readme-golden-path.md
agent-tasks/0019-recovery-playbook.md
agent-tasks/0020-example-project-refresh.md
agent-tasks/0021-agent-adapter-contract.md
agent-tasks/0022-agent-output-validation.md
agent-tasks/0023-codex-exec-adapter-hardening.md
agent-tasks/0024-claude-manual-adapter-hardening.md
agent-tasks/0025-generic-shell-adapter.md
agent-tasks/0026-agent-job-evidence-ingestion.md
agent-tasks/0027-dashboard-data-contract.md
agent-tasks/0028-dashboard-evidence-navigation.md
agent-tasks/0029-dashboard-risk-and-blockers.md
agent-tasks/0030-distribution-readiness.md
agent-tasks/0031-workflow-proposal-mode.md
agent-tasks/0032-workflow-proposal-review.md
agent-tasks/0033-workflow-verifier.md
agent-tasks/0034-limited-execution-sandbox.md
agent-tasks/0035-automatic-workflow-executor.md
agent-tasks/0036-executor-dogfood-workflow.md
agent-tasks/0037-executor-retry-resume.md
```

Do not skip directly to MCP, plugin distribution, hosted services, or dynamic workflow generation before the CLI/runtime and project state layer are solid.

## Non-Goals For The First Production Milestone

- No cloud backend.
- No hosted dashboard.
- No production database access.
- No autonomous destructive operations.
- No automatic external notifications.
- No fully dynamic workflow generation before static workflow templates are stable.
