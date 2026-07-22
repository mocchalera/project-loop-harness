# 0209: Refactoring integrated verification

- **Status:** Complete
- **Milestone:** Post-v0.5.3 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0208
- **DB schema:** remains 8

## Goal

Verify the complete staged refactor as one integrated source and distribution
surface, record durable Evidence, and close the refactoring Goal.

## Acceptance

1. Ruff, targeted tests, Skill examples, distribution tests, and full pytest
   pass on the final revision.
2. Doctor, strict validation, audit check, render, and diff check complete with
   no new findings.
3. Source, wheel, and sdist command/help smoke tests pass.
4. PCL tasks are terminal, a completion packet is emitted, and the Goal is
   closed with that packet Evidence.
