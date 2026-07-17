# 0192 Audit Evidence Impact Classification Validation

## Dogfood signal

The canonical repository contained 49 Evidence reconciliation anomalies. Before
0192, every item was an undifferentiated `human_review` finding.

With the additive impact classification applied, the same read-only audit
reported:

```json
{
  "current_durable_copy_corruption": 0,
  "current_evidence_corruption": 3,
  "current_source_drift_with_healthy_copy": 44,
  "superseded_historical_drift": 2
}
```

The audit still returned exit code 6 and retained all 49 anomalies. The new
fields identify that 44 source files drifted while their copied bytes remain
healthy, two findings belong to superseded Evidence, and three current Evidence
findings require review.

## Red proof

```text
PYTHONPATH=src pytest -q \
  tests/test_audit_commands.py::test_audit_check_classifies_evidence_mismatch_impact_without_mutation

1 failed
KeyError: 'evidence_impact'
```

## Green proof

```text
PYTHONPATH=src pytest -q \
  tests/test_audit_commands.py::test_audit_check_classifies_evidence_mismatch_impact_without_mutation

1 passed in 0.63s
```

```text
PYTHONPATH=src pytest -q \
  tests/test_audit_commands.py tests/test_crash_concurrency.py \
  tests/test_profile_ingest_dry_run.py tests/test_evidence_add.py \
  tests/test_field_feedback_0165.py

124 passed in 48.06s
```

```text
PYTHONPATH=src python -m ruff check \
  src/pcl/audit.py tests/test_audit_commands.py

All checks passed!
```

## Full regression

```text
PYTHONPATH=src pytest -q

1083 passed, 1 skipped in 267.48s
```

## Compatibility and safety

- `audit-check/v1` remains the contract version.
- Existing anomaly classifications and exit codes are unchanged.
- No schema migration or dependency was added.
- The acceptance test hashes SQLite and JSONL before and after `audit check` and
  confirms both remain byte-identical.
