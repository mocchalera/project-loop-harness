# 0188: CLI Stage 2 report-artifact handler extraction

- **Status:** Done; implemented and verified
- **Milestone:** Post-v0.5.1 maintainability
- **Priority:** P1
- **Size:** S
- **Dependency:** 0187 doctor handler extraction
- **DB schema:** remains 8

## Goal

Extract the deterministic report-artifact `pcl report` handlers from `cli.py`
while preserving generated Markdown, output, error, exit-code, and durable-state
contracts.

## Scope

1. Move `goal`, `run`, `feature`, `defect`, and `validation` report dispatch and
   JSON/text stdout selection into the existing read-only handler module.
2. Keep report query/render/write services in `reports.py`.
3. Keep parser construction, `kpi`, `skill-usage`, and top-level error handling
   in `cli.py`.
4. Characterize all five dispatch paths, exact JSON/text bytes, the sole
   permitted Markdown artifact write, and invalid-target zero-write rejection.

## Invariants

- Report Markdown remains the only permitted filesystem mutation.
- SQLite, JSONL events, outbox, Evidence, dashboard, and unrelated report files
  remain byte-identical.
- No parser, schema, dependency, provider, telemetry, or external mutation.

## Acceptance

1. Direct dispatch/output, report-only mutation, and rejection tests pass.
2. Existing report, validation, CLI, MCP, parser, Skill, and distribution tests
   pass.
3. Full Ruff and pytest pass.
4. Doctor, strict validation, render, and diff check pass.
5. Reviewable Evidence pins the result.

## Completion evidence

- `docs/evidence/0188-cli-stage2-report-artifact-handler-extraction.md`
