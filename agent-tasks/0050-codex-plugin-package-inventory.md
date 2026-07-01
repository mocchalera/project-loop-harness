# Task 0050: Codex Plugin Package Inventory

## Goal

Make the Codex plugin package boundary explicit and testable.

Dogfooding feature coverage for `F-0004` showed that the plugin manifest and
examples were tested, but the package did not have a machine-readable inventory
for the exact files intended for distribution.

## Scope

- Add `plugins/codex-project-loop/package-files.json`.
- Keep the inventory deterministic, sorted, and relative to the plugin root.
- Add regression tests that assert every listed file exists.
- Add regression tests that assert there are no unlisted package files.
- Assert manifest-controlled paths stay inside the plugin package and are
  represented in the inventory.
- Update plugin docs and task index.

## Acceptance Criteria

- `pytest tests/test_codex_plugin.py` passes.
- Full `pytest` passes.
- `pcl validate --strict --json` passes.
- `pcl render --json` returns dashboard HTML and data artifact paths.

## Do Not

- Do not add schema migrations.
- Do not add dependencies.
- Do not publish the plugin.
- Do not add automatic external service calls.
