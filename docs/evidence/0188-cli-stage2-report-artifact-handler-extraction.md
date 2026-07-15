# 0188 CLI Stage 2 report-artifact handler extraction evidence

- **Date:** 2026-07-16
- **Goal:** G-0050
- **Task:** T-0103
- **Feature:** F-0050
- **Story:** US-0048
- **Test:** TC-0113

## Implemented slice

- Added `handle_report_artifact()` to `src/pcl/read_handlers.py`.
- Moved only `goal`, `run`, `feature`, `defect`, and `validation` report service
  dispatch plus JSON/text stdout selection out of `cli.py`.
- Kept report query/render/write services in `reports.py`.
- Kept parser construction, `kpi`, `skill-usage`, and top-level error handling
  in `cli.py`.
- Added direct coverage for all five dispatch paths in JSON and text, the sole
  permitted Markdown artifact write, and invalid-target zero-write rejection.

## Verification

| Check | Result |
|---|---|
| Direct handler + report/validation contract tests | 39 passed |
| Distribution/Skill/contract CLI/MCP/KPI/skill-usage tests | 84 passed |
| Permitted filesystem change | only `reports/validation.md` |
| SQLite and `events.jsonl` bytes before/after report | identical |
| Invalid goal report | typed error, no output, no changed files |
| `ruff check .` | passed |
| Full `pytest -q` | 1068 passed, 1 skipped in 333.21s |
| Source-checkout `pcl doctor --json` | ok, no findings or warnings |
| `pcl validate --strict` | 0 errors, 29 known historical warnings |
| `git diff --check` | passed |

## Contract result

The extracted handler preserves deterministic Markdown artifacts, compact
sorted JSON, text paths, typed errors, and exit codes. The only observed write
is the requested report artifact; SQLite, JSONL events, and all other local
state bytes remain unchanged. No parser, schema, dependency, provider,
telemetry, KPI, skill-usage, or external surface changed.
