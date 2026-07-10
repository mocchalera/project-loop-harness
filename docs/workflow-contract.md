# Workflow Contract

A workflow is a YAML file under `.project-loop/workflows/`.

It describes:

- goal;
- completion criteria;
- agents;
- steps;
- budget;
- stop conditions;
- escalation rules.

The workflow runner should treat YAML as declarative configuration, not executable code.
Rule conditions are stored as strings. They may be quoted or plain scalars, so
simple comparison expressions such as `loop.iteration >= 2` remain declarative
data and are not evaluated by the YAML parser.

## Required fields

```yaml
id: defect_repair
name: Defect Repair Closed Loop
type: closed_loop
version: "0.1.0"

goal:
  description: Fix one open defect and verify no regression.
  completion: []

agents: {}
steps: []
budget: {}
stop_conditions: []
```

## Non-goals

Do not let agents generate and immediately execute arbitrary workflow code in the first milestone. Dynamic workflows can come later, behind human approval and verifier review.

## Proposal mode

Workflow proposals are review artifacts under `.project-loop/workflow-proposals/`.
They are not executable templates.

Use:

```bash
pcl workflow propose --file proposal.yaml --summary "Why this workflow should exist"
pcl workflow proposals list
pcl workflow proposals list --status proposed
pcl workflow proposals read WP-0001
pcl workflow verify --proposal WP-0001
pcl workflow verify --template feature_coverage
pcl workflow proposals approve WP-0001 --summary "Approved for local use"
pcl workflow proposals cancel WP-0001 --summary "Not needed"
```

`pcl loop run` only loads approved workflow templates from `.project-loop/workflows/`.
A proposal must not be executed directly, even when its YAML is valid.

Approval is a guarded promotion step. It validates the proposal, copies it to
`.project-loop/workflows/<workflow_id>.yaml`, and appends a
`workflow_proposal_approved` event with the promoted template path and content
hash. Approval is blocked when the workflow verifier reports errors. Cancellation
appends `workflow_proposal_cancelled` and leaves the proposal non-executable.

The verifier is a static check. It parses declarative YAML, checks agent and step
references, validates budget shape, and rejects dangerous command fragments. It
does not execute workflow commands.

## Guarded command planning and execution

Workflow command steps can be inspected with the guarded executor:

```bash
pcl workflow guard --template feature_coverage
pcl workflow guard --proposal WP-0001
pcl workflow guard --file workflow.yaml
```

Guard output uses contract `guarded-executor/v1`. The default mode is dry-run:
it parses command steps, resolves `project.commands.*` references from
`pcl.yaml`, reports allowlisted argv, and explains blocked commands.

Execution is explicit and template-only:

```bash
pcl workflow guard --template feature_coverage --execute
```

`--execute` never runs proposals or arbitrary files. It only runs allowlisted
commands from approved templates, skips blocked commands, and captures bounded,
redacted stdout/stderr under `.project-loop/evidence/guarded-executor/`. It
records a `guarded_executor_run` evidence row and appends a
`guarded_executor_executed` event. If every command is blocked, execution
returns a non-success result and does not record guarded execution evidence.

The default cap is 1 MiB per stdout/stderr stream and can be changed with
`--max-output-bytes`. Evidence records the original byte count, retained byte
count, head-retention strategy, truncation reason, timeout termination,
binary/encoding classification, and `redacted` status. `--redact-pattern` adds
repeatable Python regular expressions to the shared conservative filters.
Filters run before artifact storage and no raw-output fallback is retained.
They are not a secret scanner and do not prove that output is secret-free.

The permission packet states the actual boundary: argv list, `shell=False`,
project-root working directory, environment allowlist, and no OS, network, or
filesystem isolation. The current backend is a host subprocess, not a sandbox.
Use repeatable `--allow-env NAME` only when a command explicitly needs another
parent variable; the packet records inherited names but never their values.

For compatibility, `pcl workflow sandbox` remains an alias through the `0.3.x`
release line. It emits a deprecation warning to stderr, retains the legacy
`workflow-sandbox/v1` response key/contract and legacy Evidence identifiers, and
uses the same hardened execution implementation. Migrate scripts to
`pcl workflow guard` and the `guarded_executor` response key.

Safe `pcl` execution is limited to local validation/render/read checks such as
`pcl validate`, `pcl render`, `pcl doctor`, `pcl next`, and
`pcl workflow verify`. State-mutating commands such as `pcl feature add` are
blocked. Project command references are limited to configured local
`lint`, `typecheck`, `test`, `e2e`, and `build` commands without shell
metacharacters or blocked executables.

## Automatic executor

Approved templates can be driven by the guarded executor:

```bash
pcl loop execute executor_smoke
pcl loop execute workflow_id
pcl loop execute workflow_id --goal G-0001
pcl loop execute workflow_id --retry WR-0001
pcl loop execute workflow_id --resume WR-0001
pcl loop execute workflow_id --agent-adapter generic_shell --allow-agent-exec
```

Executor output uses contract `workflow-executor/v1`. It verifies the template,
preflights command steps through the guarded executor, creates a workflow run, executes
steps in workflow order, records workflow execution evidence, records an
automated verification, completes the run, validates state, and renders the
dashboard by default. Templates with no executable command or agent steps are
rejected before run creation.

Agent steps remain gated. A workflow with agent steps is rejected unless
`--allow-agent-exec` is supplied with an executable adapter such as
`generic_shell` or `codex_exec`. The generic shell adapter requires
`PCL_AGENT_COMMAND` and must produce `agent-output/v1` Markdown.

Blocked command steps are rejected before a workflow run is created. Safe command
failures create a run, record execution evidence, and mark the run failed.

Retry and resume are explicit. `--retry WR-0001` creates a new workflow run for a
failed or cancelled source run and records the source run id in executor events
and evidence. `--resume WR-0001` takes over an active workflow run without
creating a new run. `pcl next` surfaces these as guided actions instead of
silently re-running work.

The bundled `executor_smoke` workflow is the canonical command-only smoke test
for this path. It verifies its own template, validates state, and renders the
dashboard without requiring agent execution or project-specific commands.

## Execution states

```text
queued -> running -> passed
queued -> running -> failed
queued -> running -> blocked
queued -> cancelled
```

## Retry policy

A workflow may retry only when:

- it has remaining iteration budget;
- the failure is not identical to the previous failure;
- the next action is safe under `pcl.yaml` permissions;
- no material ambiguity blocks the step.
