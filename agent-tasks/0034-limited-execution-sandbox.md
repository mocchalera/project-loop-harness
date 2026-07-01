# Task 0034: Limited Execution Sandbox

## Goal

Add a conservative workflow command sandbox so approved workflow templates can
dry-run and optionally execute a tiny allowlist of local commands without
turning workflow YAML into arbitrary code.

Task 0033 added static workflow verification. The next gap is a controlled
runtime boundary for command steps that keeps execution explicit, local, and
evidence-backed.

## Scope

Add CLI/runtime support for:

- `pcl workflow sandbox --template workflow_id`;
- `pcl workflow sandbox --proposal WP-0001`;
- `pcl workflow sandbox --file workflow.yaml`;
- `pcl workflow sandbox --template workflow_id --execute`;

The default mode is dry-run. It should parse command steps, resolve supported
`project.commands.*` references from `pcl.yaml`, and return deterministic JSON
using contract `workflow-sandbox/v1`.

Execution is narrower than planning:

- execution is allowed only for approved workflow templates;
- execution requires explicit `--execute`;
- proposal and arbitrary file targets are dry-run only;
- safe `pcl` commands are limited to local validation/render/read checks;
- project commands are limited to configured local check/build/test command keys;
- blocked commands are skipped and reported with stable reasons;
- shell metacharacters, direct secret/state access, network/deploy tools, and
  shell interpreters are blocked;
- executed runs record evidence and append a `workflow_sandbox_executed` event.

## Acceptance criteria

- Dry-run JSON includes target metadata, verifier result, command list,
  `safe_to_run`, `blocked_reason`, and resolved argv where applicable.
- `--execute` refuses proposal and file targets with a typed JSON error.
- `--execute` runs only safe commands from approved templates.
- Executed sandbox runs write evidence under `.project-loop/evidence/` and
  append an event.
- Unsafe or state-mutating commands such as `pcl feature add`, shell pipelines,
  and `bash -c` are blocked.
- Workflow verifier failures prevent execution.
- Tests cover dry-run, execution evidence/event recording, proposal execution
  refusal, and unsafe project command blocking.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not execute workflow proposals directly.
- Do not execute arbitrary shell strings.
- Do not use `shell=True`.
- Do not add hosted services, external notifications, or cloud sandboxing.
- Do not add automatic workflow execution from `pcl loop run`.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
