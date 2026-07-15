# 0187 CLI Stage 2 doctor handler extraction evidence

- **Date:** 2026-07-16
- **Goal:** G-0049
- **Task:** T-0102
- **Feature:** F-0049
- **Story:** US-0047
- **Test:** TC-0112

## Implemented slice

- Added `handle_doctor()` to the existing `src/pcl/read_handlers.py`.
- Moved only `pcl doctor` validation orchestration, opt-in update advice, and
  JSON/text stdout selection out of `cli.py`.
- Kept `validate_project()` and `update_check.check_for_update()` as the
  service owners.
- Kept parser construction, `pcl validate`, other update commands, and
  top-level error handling in `cli.py`.
- Added exact-output and byte-snapshot tests for healthy JSON/text, update
  advice, disabled-by-default update checking, and uninitialized strict
  failure.

## Verification

| Check | Result |
|---|---|
| Direct handler + doctor/update/CLI contract tests | 53 passed |
| Distribution/Skill/contract CLI/MCP tests | 64 passed |
| Initialized `.project-loop` bytes before/after doctor | identical |
| Uninitialized strict doctor attempt | exit 1, exact output, no files |
| Update check without `--check-updates` | not invoked |
| `ruff check .` | passed |
| Full `pytest -q` | 1056 passed, 1 skipped in 247.34s |
| Source-checkout `pcl doctor --json` | ok, no findings or warnings |
| `pcl validate --strict` | 0 errors, 29 known historical warnings |
| `git diff --check` | passed |

## Contract result

The extracted handler preserves validation findings, compact sorted JSON,
text output, exit codes, opt-in update checking, and fail-open update advice.
It leaves every inspected local-state byte unchanged. No parser, state, event,
outbox, schema, dependency, provider, telemetry, or external surface changed.
