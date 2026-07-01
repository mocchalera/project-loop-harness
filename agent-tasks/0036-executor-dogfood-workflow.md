# Task 0036: Executor Dogfood Workflow

## Goal

Make the guarded workflow executor dogfood-ready by adding a bundled workflow
that can be executed safely in any initialized project.

Task 0035 added `pcl loop execute`, but operators need a known-good workflow to
exercise the executor itself without writing custom YAML or launching agents.

## Scope

Add a bundled workflow template:

- `executor_smoke`
- command-only;
- no agent adapter execution;
- only sandbox-allowlisted `pcl` commands;
- safe to run immediately after `pcl init`;
- usable as the canonical executor smoke test.

Document the executor path:

- README;
- golden path;
- implementation plan;
- task index.

Test the path:

- initialized projects include `executor_smoke.yaml`;
- `pcl workflow verify --template executor_smoke` passes;
- `pcl workflow sandbox --template executor_smoke --json` has no blocked commands;
- `pcl loop execute executor_smoke --json` completes, records evidence, records verification, and renders;
- strict validation passes after execution.

## Acceptance criteria

- `pcl init` installs `.project-loop/workflows/executor_smoke.yaml`.
- `pcl loop execute executor_smoke --json` succeeds in a fresh initialized project.
- The smoke workflow contains no agent steps and no project-specific command references.
- Tests cover init/distribution and executor smoke execution.
- Docs show the guarded automatic path.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not add external services.
- Do not auto-launch Codex or Claude.
- Do not require `PCL_AGENT_COMMAND`.
- Do not make the smoke workflow mutate project state outside `pcl`.
- Do not add arbitrary shell execution.
