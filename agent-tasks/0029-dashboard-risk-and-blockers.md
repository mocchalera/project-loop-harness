# Task 0029: Dashboard Risk And Blockers

## Goal

Make the dashboard explicitly surface risks and blockers before a human has to scan every table.

The dashboard already exposes stable data and evidence navigation. It should now answer the second dashboard design question directly:

```text
What is risky or blocked?
```

## Scope

- Add a deterministic `risk_summary` section to `dashboard-data.json`.
- Include validation errors/warnings, open escalations, open decisions, open defects, failed or blocked workflow runs, and failed or blocked agent jobs.
- Preserve normal `pcl render` behavior: rendering uses normal validation and does not require `--strict` to pass.
- Preserve normal validation-error behavior: the CLI render path still stops before writing dashboard data when normal validation fails.
- Render a "Risk & Blockers" panel in dashboard HTML near the next-action and validation panels.
- Keep rows derived from existing SQLite state, validation output, and next-action data.
- Update the dashboard data contract documentation and tests.

## Acceptance criteria

- `pcl render --json` writes `risk_summary` with stable keys:
  - `blocking`
  - `highest_severity`
  - `items`
- Each risk item has stable keys for type, severity, blocking status, human requirement, summary, command, target, and count.
- Dashboard HTML includes a "Risk & Blockers" panel.
- Open escalations and decisions appear as blocking human-required risk items.
- Validation warnings appear as non-blocking risk items.
- Failed or blocked workflow runs and agent jobs appear as risk items.
- Dashboard data remains deterministic for unchanged state.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not edit generated dashboard HTML directly.
- Do not make dashboard data the source of truth.
- Do not make rendering depend on strict validation.
- Do not add JavaScript or frontend frameworks.
- Do not add external notifications.
