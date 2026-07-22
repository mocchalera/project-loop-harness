# 0204: CLI Stage 3 entity lifecycle handlers

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.3 maintainability
- **Priority:** P1
- **Size:** M
- **Dependency:** 0188 and the frozen split contract
- **DB schema:** remains 8

## Goal

Extract Goal, Task, Feature, Story, Test, and Defect CLI orchestration from
`cli.py` without changing observable behavior or mutation ownership.

## Acceptance

1. Parser definitions and service-layer transactions remain in their current
   owners.
2. Exact JSON/text output, errors, exit codes, events, and zero-trace
   rejections are characterized and preserved.
3. Targeted tests, Skill examples, distribution tests, Ruff, and full pytest
   pass.

## Completion evidence

- `docs/evidence/0204-cli-stage3-entity-handlers.md`
- Implementation commit: `d7d38ea`
- Full regression: 1,164 passed, 1 skipped
