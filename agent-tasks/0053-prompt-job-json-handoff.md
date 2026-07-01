# Task 0053: Prompt Job JSON Handoff

## Goal

Make `pcl prompt job --json` a complete machine-readable handoff surface.

Dogfooding feature coverage for `F-0007` showed that `pcl agent command --json`
exposes output and ingest metadata, while `pcl prompt job --json` returned only
the prompt body. Automation then had to call another command or reconstruct
paths before writing agent output.

## Scope

- Keep non-JSON `pcl prompt job J-0001` as prompt text only.
- Add handoff metadata to `pcl prompt job J-0001 --json`:
  - `prompt_path`;
  - `output_path`;
  - `ingest_command`;
  - `expected_output_format`;
  - job context fields.
- Add regression tests for JSON and non-JSON behavior.
- Document the JSON shape.

## Acceptance Criteria

- `pytest tests/test_agents.py` passes.
- Full `pytest` passes.
- `pcl validate --strict --json` passes.
- No schema migration is added.

## Do Not

- Do not execute external agents.
- Do not change ingest semantics.
- Do not add dependencies.
- Do not make agents edit SQLite directly.
