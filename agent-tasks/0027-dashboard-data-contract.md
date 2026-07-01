# Task 0027: Dashboard Data Contract

## Goal

Make `.project-loop/dashboard/dashboard-data.json` a stable, versioned review surface for humans and agents.

Milestone 4 should not start by making the dashboard prettier. The next useful step is to freeze the data contract that the HTML dashboard renders from, so future dashboard improvements cannot accidentally drop state, links, or next-action metadata.

## Scope

- Add a dashboard data contract version: `dashboard-data/v1`.
- Document the top-level keys and required nested keys in `docs/dashboard-data-contract.md`.
- Keep `dashboard.html` as a deterministic view of `dashboard-data.json`.
- Add regression tests for:
  - exact top-level keys;
  - required count keys;
  - guided `next_action` metadata keys;
  - validation block keys;
  - current goal and active workflow keys;
  - agent job evidence-linkage keys;
  - evidence/report/event row keys.
- Keep rendering independent of strict validation.
- Preserve deterministic output ordering.

## Acceptance criteria

- `pcl render --json` writes dashboard data with `contract_version = "dashboard-data/v1"`.
- Tests lock the dashboard data contract shape without requiring a browser.
- Existing dashboard HTML rendering still works.
- Existing strict validation behavior is unchanged.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not edit generated dashboard HTML directly.
- Do not make dashboard rendering depend on `pcl validate --strict`.
- Do not add frontend frameworks or assets.
- Do not make `.project-loop/dashboard/dashboard-data.json` the source of truth.
