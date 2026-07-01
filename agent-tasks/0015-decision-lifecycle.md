# Task 0015: Decision Lifecycle

## Goal

Add guarded CLI/runtime commands for durable human decisions.

Escalations represent human attention required, but the durable result of a human choice should be structured state instead of only free text in an escalation summary.

## Scope

Add CLI/runtime support for:

- `pcl decision open --question "..." --recommendation "..." [--blocks-json '[...]']`;
- `pcl decision resolve DEC-0001 --selected-option "..." --reason "..."`;
- `pcl decision waive DEC-0001 --reason "..."`;
- `pcl decision list [--status open]`;
- `pcl decision read DEC-0001`.

Integrate decision state with `pcl next`:

- open escalations should still be surfaced first;
- open decisions should be surfaced before continuing normal work;
- `pcl next --strict` must still route strict validation failures before decision routing.

## Acceptance criteria

- Decision mutations append events.
- JSON output is predictable and typed.
- Invalid transitions return typed JSON errors.
- `--blocks-json` must parse as a JSON array and defaults to `[]`.
- Open decisions appear in dashboard counts/tables without hand-editing dashboard output.
- `pcl next --json` returns a `resolve_decision` action when an open decision exists and no open escalation exists.
- Tests cover open, resolve, waive, invalid transitions, next-action routing, dashboard visibility, and strict validation precedence.
- No schema migration is added.

## Do not

- Do not add external messaging.
- Do not auto-resolve decisions from model output.
- Do not make dashboard rendering depend on strict validation.
- Do not let agents mutate SQLite directly.
