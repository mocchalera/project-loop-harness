# 0208: CLI Stage 4 parser construction split

- **Status:** Planned
- **Milestone:** Post-v0.5.3 maintainability
- **Priority:** P1
- **Size:** M
- **Dependency:** 0207
- **DB schema:** remains 8

## Goal

Split parser construction by command family while retaining one public
`build_parser()` facade and the existing source/wheel/sdist entry points.

## Acceptance

1. Commands, flags, defaults, choices, help text, aliases, and parser errors
   remain unchanged.
2. Skill example parsing and complete help smoke checks pass.
3. Distribution tests, Ruff, full pytest, and source/wheel/sdist smoke pass.

