# Task 0020: Example Project Refresh

## Goal

Refresh the bundled example project configs so new operators can copy an example, initialize Project Loop Harness, and run the documented local loop without guessing which settings are current.

0018 and 0019 documented the golden path and recovery path. The `examples/` directory should now reflect those docs instead of carrying only older minimal `pcl.yaml` files.

## Scope

- Update `examples/python-cli/pcl.yaml` and `examples/nextjs/pcl.yaml` to include the current `project_loop`, `loop`, `permissions`, and `dashboard` sections.
- Add README files that explain how to copy each example into a temporary project, run `pcl init`, validate, render, and use `pcl next`.
- Link examples from the root README.
- Add lightweight tests that parse the example configs and smoke-test `pcl init`, `pcl validate`, and `pcl render` against copied examples.

## Acceptance criteria

- Example configs include `project_loop.version`, `project_loop.schema_version`, `loop`, and `dashboard`.
- Example configs explicitly protect `.project-loop/project.db` and `.project-loop/events.jsonl`.
- Example docs mention `pcl next --json`, `pcl validate --strict --json`, and `docs/recovery-playbook.md`.
- Copying each example into a temporary directory and running `pcl init`, `pcl validate --strict --json`, and `pcl render --json` succeeds.
- No schema migration is added.
- No generated dashboard HTML is hand-edited.

## Do not

- Do not add dependencies.
- Do not make examples run package managers in tests.
- Do not commit generated `.project-loop/` state inside `examples/`.
- Do not add external services, hosting, or notifications.
