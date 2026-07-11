# 0149a: Adaptive Entry dogfood and release gate

- **Status:** Done; human-reviewed 2026-07-11
- **Milestone:** v0.4.2 Adaptive Entry
- **Priority:** P0
- **Dependencies:** 0146–0149
- **DB schema:** remains 8

Exercise PLH itself and at least one external repository with clear,
ambiguous, and high-risk tasks. Record recommendation, policy explanation,
override decision, outcome, confusion, and local timing as project-local
Evidence. Direct route must add no mandatory human step; resolver p95 target is
below 50 ms on the deterministic fixture batch.

The gate also compares audit output to
`docs/canonical-state-baseline-v0.4.2.md`: no new anomaly is allowed. Full
pytest, ruff, Python matrix, Windows smoke, package-data, sdist/wheel, and clean
install checks are required. A human reviews dogfood conclusions; this task
does not self-approve route quality.
