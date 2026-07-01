# Task 0004: Improve Dashboard Renderer

## Goal

Turn the initial dashboard into a useful control dashboard.

## Read first

- `docs/dashboard-design.md`
- `src/pcl/renderer.py`

## Scope

Add panels for:

- current goal;
- active workflow run;
- agent jobs;
- verification results;
- escalations;
- budget usage;
- recent events;
- evidence links.

Add:

- deterministic ordering;
- clear empty states;
- validation warning block;
- generated JSON data file.

## Acceptance criteria

- `pcl render` produces valid HTML without external assets.
- Dashboard makes next human action obvious.
- Dashboard says when it was generated and from what DB.
- Tests check key strings appear in output.

## Do not

- Do not introduce a frontend build system.
- Do not require network resources.
