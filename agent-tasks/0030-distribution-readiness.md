# Task 0030: Distribution Readiness

## Goal

Finish the first distribution milestone by proving that the local runtime can be installed outside editable development mode and that distribution wrappers remain explicit, local, and dependency-light.

Milestone 5 is not about publishing to hosted marketplaces yet. It is about making the package, Codex plugin scaffold, optional MCP bridge, and GitHub Action example safe to hand to another local project.

## Scope

- Add a wheel-install smoke test that installs `project-loop-harness` into a fresh virtual environment.
- Verify installed console scripts:
  - `pcl`
  - `pcl-mcp`
- Verify installed package resources by running, in a temporary project:
  - `pcl init`
  - `pcl doctor`
  - `pcl validate`
  - `pcl render`
  - `pcl next --json`
- Add a reusable composite GitHub Action for project-loop validation.
- Keep the repo workflow wired to that action without assuming this repo has committed `.project-loop` state.
- Document the local distribution smoke path and GitHub Action usage.
- Keep Codex plugin and MCP examples as opt-in wrappers around the installed Python runtime.

## Acceptance criteria

- A fresh virtualenv can install the built wheel and run `pcl --help`.
- `pcl init` from the installed wheel writes bundled templates, workflows, and the project-control-loop skill.
- `pcl validate`, `pcl render`, and `pcl next --json` pass in the initialized temporary project.
- `pcl-mcp --help` works from the installed wheel.
- `.github/actions/project-loop-validate/action.yml` exposes root, strict, render, and install-command inputs.
- `.github/workflows/project-loop-validate.yml` uses the reusable action.
- Tests cover the wheel-install smoke and GitHub Action contract.
- No hosted backend, external notification, marketplace publication, or schema migration is added.

## Do not

- Do not publish to PyPI.
- Do not publish to a plugin marketplace.
- Do not add cloud services.
- Do not auto-start MCP servers.
- Do not require committed `.project-loop` state in this repository.
