# 0185 CLI Stage 2 guide handler extraction evidence

- **Date:** 2026-07-15
- **Goal:** G-0047
- **Task:** T-0100
- **Feature:** F-0047
- **Story:** US-0045
- **Test:** TC-0110

## Implemented slice

- Added `src/pcl/read_handlers.py` with the bounded `pcl guide` handler.
- Moved guide orchestration and JSON/text stdout selection out of `cli.py`.
- Kept parser construction, global-option handling, and top-level typed-error
  handling in `cli.py`.
- Added direct byte-parity and typed-error tests in
  `tests/test_read_handlers.py`.
- Kept all other command families unchanged.

## Verification

| Check | Result |
|---|---|
| Direct handler + existing guide tests | 8 passed |
| Skill/parser/distribution tests | 65 passed |
| Public module smoke from an uninitialized root | command-guide/v1, 5 topics |
| `ruff check .` | passed |
| Full `pytest -q` | 1048 passed, 1 skipped in 217.81s |
| Source-checkout `pcl doctor --json` | ok, no findings or warnings |
| `pcl validate --strict` | 0 errors, 29 known historical warnings |
| `pcl render --json` | passed |
| `git diff --check` | passed |

## Contract result

The extracted handler produces the existing renderer bytes for text and the
existing sorted compact JSON bytes for JSON. Unknown topics still raise the
same `InvalidInputError` before writing output, and existing CLI tests prove
that guide remains deterministic and filesystem-neutral before initialization.
No state, event, parser, schema, dependency, provider, telemetry, or external
surface changed.
