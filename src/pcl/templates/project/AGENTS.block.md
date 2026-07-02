<!-- project-loop-harness:start -->
## Project Loop Harness

This repository uses Project Loop Harness.

Rules for coding agents:

- Do not edit `.project-loop/project.db` directly.
- Do not edit `.project-loop/dashboard/dashboard.html` directly.
- Do not read or parse `.project-loop/dashboard/dashboard.html` as project state; it is a human-only view.
- Use `pcl` JSON commands, reports, evidence paths, or `.project-loop/dashboard/dashboard-data.json` for machine context.
- Use `pcl` commands to mutate project-loop state.
- After meaningful state changes, run `pcl validate` and `pcl render`.
- Evidence is required for status changes.
- In non-empty projects, inspect with `pcl init --dry-run --json` before applying initialization changes.
- For behavior changes, capture user stories and test cases with `pcl story` and `pcl test`.
- Human approval is required for database migrations, dependency additions, auth/billing changes, production config changes, and destructive operations.
- Prefer small, verifiable changes.
- If the same failure repeats, stop and escalate instead of looping indefinitely.
<!-- project-loop-harness:end -->
