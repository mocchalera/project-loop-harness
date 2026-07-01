# Task 0057: Executor No-Executable-Step Guard

## Goal

Prevent `pcl loop execute` from creating successful no-op workflow runs for templates that contain no executable command or agent steps.

## Scope

- Detect approved workflow templates whose steps contain neither command steps nor agent steps.
- Reject those templates before creating a workflow run.
- Return a typed JSON error with `workflow_id`, `command_count`, and `agent_step_count`.
- Keep workflow verification behavior unchanged, because rules-only workflows may still be valid review artifacts.
- Add regression coverage for a rules-only workflow that verifies successfully but cannot be executed.

## Acceptance Criteria

- `pcl workflow verify --template rules_only_auto --json` can still pass for a structurally valid rules-only workflow.
- `pcl loop execute rules_only_auto --json` returns `invalid_input`.
- No workflow run is created for the rejected executor call.
- Existing command-only and agent-only executor paths continue to pass.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not remove or reinterpret workflow `rules`.
- Do not make the verifier reject rules-only workflow YAML.
- Do not create placeholder evidence for work that did not execute.
- Do not add hosted execution or external queues.
