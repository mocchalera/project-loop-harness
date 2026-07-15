# 0187: CLI Stage 2 doctor handler extraction

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.1 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0186 loop-status handler extraction
- **DB schema:** remains 8

## Goal

Extract the complete read-only `pcl doctor` handler from `cli.py` while
preserving validation, opt-in update advice, output, exit-code, and
zero-mutation contracts.

## Scope

1. Move doctor validation orchestration and JSON/text output selection into the
   existing read-only handler module.
2. Include the existing explicit `--check-updates` path without changing its
   disabled-by-default or fail-open behavior.
3. Keep parser construction, `pcl validate`, other update commands, and
   top-level error handling in `cli.py`.
4. Characterize healthy JSON/text bytes, update advice, strict failure, and
   complete `.project-loop` byte stability.

## Invariants

- `validate_project()` and `update_check.check_for_update()` retain their
  service ownership and behavior.
- No update check occurs unless `--check-updates` is selected.
- No state, file, event, outbox, parser, schema, dependency, provider,
  telemetry, or external mutation.

## Acceptance

1. Direct handler parity and filesystem-neutrality tests pass.
2. Existing doctor, update-check, CLI, MCP, parser, Skill, and distribution
   tests pass.
3. Full Ruff and pytest pass.
4. Doctor, strict validation, render, and diff check pass.
5. Reviewable Evidence pins the result.

## Completion evidence

- `docs/evidence/0187-cli-stage2-doctor-handler-extraction.md`
