# Task 0061: Context Pack v1

## Goal

Add a read-only context packaging command so PM agents can hand focused,
budget-aware project-loop context to worker agents without dumping full project
history or parsing generated dashboard HTML.

## Scope

- Add `pcl context pack --job J-0001`.
- Support `--role` for the intended reader role.
- Support `--max-tokens` as an approximate budget control.
- Return `context-pack/v1` metadata in JSON mode:
  - target job;
  - reader role;
  - approximate budget;
  - included and omitted sections;
  - source commands;
  - source paths;
  - generated Markdown.
- Include goal, workflow run, job, evidence, verification, human queue, recent
  event, and prompt context when budget allows.
- Keep the command read-only and deterministic.

## Acceptance Criteria

- `pcl context pack --job J-0001` prints Markdown.
- `pcl context pack --job J-0001 --json` returns `context-pack/v1`.
- Small `--max-tokens` values report truncation metadata instead of failing.
- The package explicitly warns agents not to use generated dashboard HTML as
  machine context.
- `pytest tests/test_context.py` passes.
- Full `pytest` passes.
- `pcl validate --strict --json` passes.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not write context packs to disk in v1.
- Do not read or parse generated dashboard HTML.
- Do not add new tables or columns.
- Do not execute external agents.
- Do not make context packaging mutate project-loop state.
