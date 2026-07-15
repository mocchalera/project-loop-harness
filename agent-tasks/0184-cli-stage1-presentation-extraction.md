# 0184: CLI Stage 1 presentation extraction

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.1 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0175 frozen split contract and verified v0.5.1 publication
- **DB schema:** remains 8

## Goal

Complete Stage 1 of the frozen CLI split contract by moving pure JSON and text
presentation helpers out of `cli.py` and `commands.py` without changing any
observable behavior.

## Scope

1. Add a narrow presentation module with no project-state or database access.
2. Move pretty JSON, impact summary, context-check summary, and start/next/finish
   text formatting into it.
3. Preserve the existing `commands.to_pretty_json` import surface.
4. Add direct characterization tests for ordering, optional lines, truncation,
   Unicode JSON, and compatibility imports.
5. Run the Stage 1 acceptance gate from
   `docs/maintainer-entry-hardening.md`.

## Invariants

- Parser definitions and dispatch remain in `cli.py`.
- Service functions, transactions, events, output keys, text, errors, exit
  codes, human gates, and generated artifacts do not change.
- No dependency, schema, migration, provider, telemetry, or external write.

## Acceptance

1. Presenter unit tests and affected CLI tests pass.
2. Skill-parser and distribution tests pass.
3. Full Ruff and pytest pass.
4. Source-checkout doctor, strict validation, render, and diff check pass.
5. Reviewable Evidence pins the command output and changed-file summary.

## Completion evidence

- `docs/evidence/0184-cli-stage1-presentation-extraction.md`
- Full regression: 1045 passed, 1 skipped
- Strict validation: 0 errors
