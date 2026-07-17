# 0192: Audit Evidence Impact Classification

- **Status:** Implemented; awaiting Story approval
- **Milestone:** v0.5.2 Dogfood Hardening
- **Priority:** P0
- **Size:** S
- **Dependency:** 0191 field review and copied Evidence support
- **DB schema:** remains 8

## Problem

Dogfooding produced many `pcl audit check` evidence mismatches, but every
mismatch currently appears as the same `human_review` anomaly. Operators must
manually inspect manifests to distinguish harmless source-path drift from a
damaged durable copy or evidence that has already been superseded.

## Scope

1. Preserve `audit-check/v1`, anomaly classifications, and exit codes.
2. Add a deterministic `evidence_impact` to evidence reconciliation anomalies.
3. Distinguish superseded historical drift, current source drift with a healthy
   durable copy, current durable-copy corruption, and other current evidence
   corruption.
4. Add aggregate mismatch counts by impact.
5. Keep `pcl audit check` read-only.

## Acceptance

1. Superseded Evidence drift is labeled `superseded_historical_drift` and names
   its replacement Evidence.
2. A rewritten source with an intact copied member is labeled
   `current_source_drift_with_healthy_copy`.
3. A missing or hash-mismatched copied member is labeled
   `current_durable_copy_corruption`.
4. Aggregate impact counts match the emitted anomalies.
5. Existing exit code 6 and `human_review` classification remain unchanged.
6. Targeted and full regression tests pass.
