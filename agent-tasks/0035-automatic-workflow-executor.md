# Task 0035: Automatic Workflow Executor

## Goal

Add a guarded automatic workflow executor that can drive an approved workflow
template end to end through the existing `pcl` state machine.

Task 0034 introduced a limited command sandbox. The next step is to connect
workflow run creation, command execution, agent adapter execution, evidence,
verification, completion, and dashboard rendering behind one explicit command.

## Scope

Add CLI/runtime support for:

- `pcl loop execute workflow_id [--goal G-0001] [--defect D-0001]`;
- `--agent-adapter manual|generic_shell|codex_exec`;
- `--allow-agent-exec`;
- `--timeout-seconds N`;
- `--no-auto-verify`;
- `--no-complete`;
- `--close-goal`;
- `--no-render`.

Executor behavior:

- verifies the approved workflow template before mutation;
- preflights command steps with the workflow sandbox allowlist;
- rejects blocked command steps before creating a workflow run;
- rejects agent steps unless `--allow-agent-exec` uses an executable adapter;
- creates a workflow run through the existing runner;
- executes steps in workflow order;
- runs command steps with `shell=False` using the sandbox command executor;
- runs explicit agent adapter commands and ingests agent output;
- records workflow execution evidence under `.project-loop/evidence/`;
- appends `workflow_execution_started` and `workflow_execution_finished` events;
- records an approved automated verification by default when all steps pass;
- completes the workflow run by default when verification is approved;
- optionally closes the goal when `--close-goal` is supplied;
- validates and renders at the end unless `--no-render` is supplied.

## Acceptance criteria

- `pcl loop execute --json` returns deterministic `workflow-executor/v1` JSON.
- Command-only workflows can execute, verify, complete, and render automatically.
- Agent workflows require explicit `--allow-agent-exec`.
- Generic shell adapter workflows can execute in tests with a local
  `PCL_AGENT_COMMAND`.
- Blocked command steps produce a typed JSON error before a run is created.
- Safe command failures mark the workflow run failed and return non-zero.
- Every state mutation appends events.
- Execution writes evidence and links the evidence id in the finish event.
- Tests cover command-only success, agent-gate refusal, generic-shell success,
  blocked-command refusal, and command failure.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not execute workflow proposals directly.
- Do not add hosted runners or external services.
- Do not execute agent adapters unless explicitly requested with
  `--allow-agent-exec`.
- Do not bypass the sandbox for command steps.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
