# 0186: CLI Stage 2 loop-status handler extraction

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.1 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0185 guide handler extraction
- **DB schema:** remains 8

## Goal

Extract the complete read-only `pcl loop status` handler from `cli.py` while
preserving its datastore, output, and zero-mutation contracts.

## Scope

1. Move loop-status orchestration and JSON/text output selection into the
   existing read-only handler module.
2. Keep parser construction, other loop subcommands, and top-level error
   handling in `cli.py`.
3. Characterize compact JSON and pretty text bytes.
4. Prove all `.project-loop` file bytes remain unchanged after a status read.
5. Preserve the typed not-initialized rejection with no output or files.

## Invariants

- `loop_status()` remains the query service and retains row ordering.
- No state, file, event, outbox, parser, schema, dependency, provider,
  telemetry, or external mutation.
- No mutating `pcl loop` subcommand moves in this slice.

## Acceptance

1. Direct handler parity, filesystem-neutrality, and rejection tests pass.
2. Existing defect, CLI, MCP, parser, Skill, and distribution tests pass.
3. Full Ruff and pytest pass.
4. Doctor, strict validation, render, and diff check pass.
5. Reviewable Evidence pins the result.

## Completion evidence

- `docs/evidence/0186-cli-stage2-loop-status-handler-extraction.md`
- Full regression: 1051 passed, 1 skipped
- Strict validation: 0 errors
