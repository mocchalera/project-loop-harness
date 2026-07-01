# Task 0033: Workflow Verifier

## Goal

Add a deterministic workflow verifier before dynamic workflow proposals can become runnable templates.

Tasks 0031 and 0032 made workflow proposals durable and added human approval. The remaining gap is a machine-checkable review step that catches unsafe or structurally inconsistent workflow YAML before approval.

## Scope

Add CLI/runtime support for:

- `pcl workflow verify --file workflow.yaml`;
- `pcl workflow verify --proposal WP-0001`;
- `pcl workflow verify --template workflow_id`.

The verifier should check:

- required workflow fields and YAML parseability;
- supported workflow type;
- goal, agents, steps, budget, and stop condition shape;
- step IDs and agent references;
- allowed agent modes;
- dangerous command fragments and forbidden executable keys;
- conservative budget bounds.

Integrate verifier results with approval:

- `pcl workflow proposals approve` must reject proposals with verifier errors;
- approval event payload should include verifier summary;
- approved workflow templates should still be strict-validated with the same verifier.

## Acceptance criteria

- Verification JSON output is deterministic and typed.
- Verification failure exits non-zero without mutating state.
- Valid bundled-style workflow YAML verifies successfully.
- Unsafe command fragments such as `rm -rf`, `sudo`, shell pipelines, redirects, or direct `.project-loop/project.db` access are verifier errors.
- Invalid step references are verifier errors.
- Proposal approval is blocked when verifier errors exist.
- `pcl validate --strict` catches approved workflow templates that fail the verifier.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not execute workflow commands.
- Do not auto-approve workflow proposals.
- Do not add sandbox execution yet.
- Do not add external services or hosted verification.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
