# Task 0051: MCP Render Artifact Paths

## Goal

Make the optional local MCP render bridge return the same generated dashboard
artifacts that the CLI exposes.

Dogfooding feature coverage for `F-0005` showed that `pcl render --json` returns
both the dashboard HTML path and dashboard data path, while MCP
`render_dashboard` only returned the HTML path.

## Scope

- Keep `render_dashboard` unavailable in read-only MCP approval mode.
- In `local-render` approval mode, return both:
  - `dashboard`;
  - `data_path`.
- Verify both generated files exist after the MCP tool call.
- Document the structured result shape.

## Acceptance Criteria

- `pytest tests/test_mcp_server.py` passes.
- Full `pytest` passes.
- `pcl validate --strict --json` passes.
- No schema migration is added.

## Do Not

- Do not add mutating MCP tools.
- Do not add external transports.
- Do not add dependencies.
- Do not weaken the root-boundary argument rejection.
