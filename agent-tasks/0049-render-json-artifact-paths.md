# Task 0049: Render JSON Artifact Paths

## Goal

Make `pcl render --json` return all generated dashboard artifact paths.

Dogfooding F-0003 showed that the command writes both `dashboard.html` and `dashboard-data.json`, but JSON output only returned the HTML path. Agents then had to know the data artifact path out of band.

## Scope

Update `pcl render --json` to return:

- `path`: generated dashboard HTML path;
- `data_path`: generated dashboard data JSON path;
- `ok`: true.

Keep text output unchanged.

## Acceptance criteria

- `pcl render --json` includes `data_path`.
- Both returned paths exist after rendering.
- Existing validation-before-render behavior remains unchanged.
- Distribution and golden-path smoke tests assert the data path exists.
- No schema migration is added.

## Do not

- Do not edit generated dashboard HTML directly.
- Do not make dashboard data the source of truth.
- Do not change the dashboard data contract version.
- Do not add external dependencies.
