# 0185: CLI Stage 2 guide handler extraction

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.1 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0184 presentation extraction
- **DB schema:** remains 8

## Goal

Begin Stage 2 of the frozen CLI split by extracting the complete `pcl guide`
read-only handler from `cli.py` without changing its observable contract.

## Scope

1. Add a narrow read-only handler module.
2. Move guide orchestration and stdout selection into the handler.
3. Keep parser construction and top-level error handling in `cli.py`.
4. Directly characterize text bytes, JSON bytes, typed error propagation, and
   zero output on rejection.
5. Preserve the existing pre-initialization zero-mutation CLI tests.

## Invariants

- No state, file, event, database, parser, command-guide payload, or renderer
  mutation.
- No output, JSON, typed error, or exit-code change.
- No dependency, schema, migration, provider, telemetry, or external write.
- No other command family moves in this slice.

## Acceptance

1. Direct handler tests and all existing command-guide tests pass.
2. Parser, Skill example, and distribution tests pass.
3. Full Ruff and pytest pass.
4. Doctor, strict validation, render, and diff check pass.
5. Reviewable Evidence pins the result.

## Completion evidence

- `docs/evidence/0185-cli-stage2-guide-handler-extraction.md`
- Full regression: 1048 passed, 1 skipped
- Strict validation: 0 errors
