# Task 0007: Optional MCP Server

## Goal

Expose safe `pcl` read operations through an MCP server, then plan guarded write operations.

## Scope

Start with read-only tools:

- `get_status`;
- `list_features`;
- `list_defects`;
- `list_escalations`;
- `render_dashboard` only if local write permission is explicit.

Later guarded tools:

- `create_goal`;
- `add_feature`;
- `open_defect`;
- `record_verification`.

## Acceptance criteria

- MCP server can be run locally.
- It never exposes secrets.
- It respects project root boundaries.
- Mutating tools require an explicit approval mode.

## Do not

- Do not implement external SaaS sync here.
- Do not expose arbitrary shell execution.
