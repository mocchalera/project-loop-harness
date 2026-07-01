# Task 0032: Workflow Proposal Review

## Goal

Add a guarded human review lifecycle for workflow proposals.

Task 0031 made proposed workflows durable but non-executable. This task lets a human explicitly approve a proposal into `.project-loop/workflows/` or cancel it, without adding dynamic generation or automatic execution.

## Scope

Add CLI/runtime support for:

- `pcl workflow proposals approve WP-0001 --summary "..."`;
- `pcl workflow proposals cancel WP-0001 --summary "..."`;
- status-aware `pcl workflow proposals list`;
- status-aware `pcl workflow proposals read WP-0001`.

Review state is derived from append-only events:

- `workflow_proposed`;
- `workflow_proposal_approved`;
- `workflow_proposal_cancelled`.

Approval copies the validated proposal YAML into `.project-loop/workflows/<workflow_id>.yaml`. Only that approved workflow template can be executed by `pcl loop run`.

## Acceptance criteria

- Approval appends `workflow_proposal_approved`.
- Cancellation appends `workflow_proposal_cancelled`.
- JSON output is predictable and typed.
- Invalid transitions return typed JSON errors.
- Approved proposals become runnable workflow templates.
- Proposed and cancelled proposals remain non-executable.
- List/read include derived `status`, review summary, review timestamp, approved workflow path, and content hash.
- `pcl next --json` surfaces proposed workflow review before goal continuation but after active workflow and defect handling.
- `pcl validate --strict` catches approved proposal events whose promoted workflow template is missing, invalid, mismatched, or has a changed content hash.
- Dashboard data and HTML show proposal review status without depending on strict validation.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not execute workflow proposals directly.
- Do not generate workflows from model output.
- Do not auto-approve or auto-cancel proposals.
- Do not add hosted services or external dependencies.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
