# Task 0013: Validation Diagnostics

## Goal

Connect strict validation failures to human-reviewable diagnostics and the next-action loop.

`pcl validate --strict` can now detect state and audit-log inconsistencies. This task should make those findings easier to route without attempting unsafe automatic repair.

## Scope

Add CLI/runtime support for:

- `pcl report validation`;
- `pcl report validation --strict`;
- `pcl next --strict`.

When strict validation fails, `pcl next --strict` should recommend generating a validation report instead of continuing normal workflow execution.

## Acceptance criteria

- Validation reports are deterministic Markdown files under `.project-loop/reports/`.
- Validation report JSON includes `ok`, `errors`, `warnings`, `strict`, and suggested next actions.
- `pcl next --strict --json` returns a `resolve_validation_errors` action when strict validation fails.
- Normal `pcl next` remains backward-compatible.
- No automated repair or destructive action is introduced.
- Tests cover strict failure routing and validation report generation.

## Do not

- Do not mutate SQLite or JSONL during validation reporting.
- Do not auto-repair audit-log or state inconsistencies.
- Do not make dashboard rendering depend on strict validation.
