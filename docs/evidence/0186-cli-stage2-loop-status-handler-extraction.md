# 0186 CLI Stage 2 loop-status handler extraction evidence

- **Date:** 2026-07-16
- **Goal:** G-0048
- **Task:** T-0101
- **Feature:** F-0048
- **Story:** US-0046
- **Test:** TC-0111

## Implemented slice

- Added `handle_loop_status()` to the existing `src/pcl/read_handlers.py`.
- Moved only `pcl loop status` orchestration and JSON/text stdout selection out
  of `cli.py`.
- Kept `loop_status()` as the datastore query service.
- Kept parser construction, typed-error handling, and every mutating loop
  subcommand in `cli.py`.
- Added compact JSON, pretty text, typed rejection, and full `.project-loop`
  byte-snapshot tests.

## Verification

| Check | Result |
|---|---|
| Direct handler + defect/CLI contract tests | 40 passed |
| MCP/parser/Skill/distribution tests | 67 passed |
| Initialized `.project-loop` bytes before/after status | identical |
| Uninitialized status attempt | typed error, no output, no files |
| `ruff check .` | passed |
| Full `pytest -q` | 1051 passed, 1 skipped in 465.11s |
| Source-checkout `pcl doctor --json` | ok, no findings or warnings |
| `pcl validate --strict` | 0 errors, 29 known historical warnings |
| `pcl render --json` | passed |
| `git diff --check` | passed |

## Contract result

The extracted handler preserves compact sorted JSON and pretty text bytes,
continues to surface the same not-initialized error, and leaves every tracked
local-state byte unchanged. No parser, state, event, outbox, schema, dependency,
provider, telemetry, or external surface changed.
