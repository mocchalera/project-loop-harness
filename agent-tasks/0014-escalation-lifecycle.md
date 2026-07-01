# Task 0014: Escalation Lifecycle

## Goal

Add guarded CLI/runtime commands for creating, resolving, and cancelling human escalations.

The harness can now detect validation and workflow issues, but human-required ambiguity must be represented as durable state instead of free text in reports.

## Scope

Add CLI/runtime support for:

- `pcl escalation open --severity high --question "..." --recommendation "..." [--run WR-0001]`;
- `pcl escalation resolve ESC-0001 --summary "..."`;
- `pcl escalation cancel ESC-0001 --summary "..."`;
- `pcl escalation list [--status open]`;
- `pcl escalation read ESC-0001`.

Integrate escalation state with `pcl next`:

- open escalations should be surfaced before continuing normal work;
- if an active workflow has a latest verification result of `needs_human` and no open escalation for that run, `pcl next` should suggest `pcl escalation open ...`;
- `pcl next --strict` must still route strict validation failures before escalation routing.

## Acceptance criteria

- Escalation mutations append events.
- JSON output is predictable and typed.
- Invalid transitions return typed JSON errors.
- Open escalations appear in dashboard counts/tables without hand-editing dashboard output.
- `pcl next --json` returns a `resolve_escalation` action when an open escalation exists.
- `pcl next --json` returns an `open_escalation` action when a workflow has a `needs_human` verification and no open escalation.
- Tests cover open, resolve, cancel, invalid transitions, next-action routing, and dashboard visibility.
- No schema migration is added.

## Do not

- Do not send Slack/email/GitHub messages.
- Do not add hosted services or external dependencies.
- Do not auto-resolve escalations.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
- Do not make dashboard rendering depend on strict validation.
