# 0205: CLI Stage 3 execution and Evidence handlers

- **Status:** Planned
- **Milestone:** Post-v0.5.3 maintainability
- **Priority:** P1
- **Size:** M
- **Dependency:** 0204
- **DB schema:** remains 8

## Goal

Extract Loop, Workflow, Jobs, Agent, Evidence, Verification, Decision,
Escalation, and checkpoint CLI orchestration while preserving every mutation,
event, outbox, artifact, and rejection contract.

## Acceptance

1. Services retain transaction and event ownership.
2. Handler parity and failure zero-trace tests cover each moved family.
3. Targeted tests, Skill examples, distribution tests, Ruff, and full pytest
   pass.

