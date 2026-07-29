# P0-A Medium review fail-first evidence

Date: 2026-07-30

Base commit:
`91904f3718f2a45b14e0be2d04caa6024cd5700b`

Command:

```text
PYTHONPATH=src pytest -q \
  tests/test_validation_projection.py::test_validate_target_with_missing_database_is_typed_and_read_only \
  tests/test_validation_projection.py::test_validate_target_keeps_active_agent_operational_safety_finding \
  tests/test_mutation_tail.py::test_render_receipt_retries_once_when_state_changes_during_render \
  tests/test_mutation_tail.py::test_invalid_auto_render_is_top_level_partial_and_recovery_diagnoses_config
```

Result:

```text
FFFF
4 failed in 0.67s
```

Observed failures:

1. Missing-database target validation returned exit 4 with
   `data_store_error: no such table: tasks` after the target resolver created
   `project.db`.
2. `agent_concurrency_exceeded` was absent from projected finding detail.
3. A mutation inserted during render produced only one render attempt.
4. Invalid `dashboard.auto_render` returned only nested tail diagnostics and
   no additive top-level committed/partial contract.
