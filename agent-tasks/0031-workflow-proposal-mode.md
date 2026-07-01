# Task 0031: Workflow Proposal Mode

## Goal

Add a non-executable workflow proposal mode before dynamic workflows can become runnable templates.

Milestone 6 starts with a safety boundary: generated or hand-authored workflow ideas must land as review artifacts, not as executable workflow templates.

## Scope

- Add `pcl workflow propose --file proposal.yaml [--summary "..."]`.
- Store proposals under `.project-loop/workflow-proposals/WP-0001.yaml`.
- Do not copy proposals into `.project-loop/workflows/`.
- Append `workflow_proposed` events for proposal creation.
- Add `pcl workflow proposals list`.
- Add `pcl workflow proposals read WP-0001`.
- Validate proposed YAML with the existing workflow YAML parser and required workflow fields.
- Add strict validation checks for proposal files and their `workflow_proposed` events.
- Show workflow proposal count/table in dashboard data and HTML.
- Keep `pcl loop run` limited to approved templates under `.project-loop/workflows/`.

## Acceptance criteria

- Proposal creation writes a deterministic file under `.project-loop/workflow-proposals/`.
- Proposal creation appends a `workflow_proposed` event.
- JSON output is predictable and typed.
- Invalid YAML and missing required fields return typed JSON errors.
- Proposal list/read return deterministic JSON.
- `pcl validate --strict` catches invalid proposal YAML, missing proposal events, missing proposal files, and event/file mismatches.
- Dashboard data includes workflow proposal count and rows.
- `pcl loop run WP-0001` or a proposed workflow id does not execute a proposal directly.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not approve or promote proposals yet.
- Do not execute proposals.
- Do not add dynamic workflow generation.
- Do not add sandbox execution.
- Do not let agents edit `.project-loop/project.db` directly.
