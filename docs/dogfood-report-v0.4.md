# v0.4 Dogfood KPI Report

This template records the v0.4.0 Dogfood Operations measurements for PLH itself
and one external repository. Actual measurements are intentionally left blank;
operators fill them during dogfood runs.

## Measurement contract

Run the local read-only report with:

```bash
PYTHONPATH=src python -m pcl --root <repo> report kpi --json
PYTHONPATH=src python -m pcl --root <repo> report kpi --since YYYY-MM-DD --json
```

During dogfood, always generate measured context packs with `--record-usage`:

```bash
PYTHONPATH=src python -m pcl --root <repo> context pack --task T-XXXX --record-usage --json
```

The `context_pack` section covers only these explicit opt-in runs. Packs created
without `--record-usage` remain fully read-only and cannot be reconstructed as
usage measurements later. All measurements are local; no telemetry or external
submission occurs.

`master_brief_tokens_saved` is not calculated by `pcl report kpi`. Measure it
manually by applying the deterministic `charclass/v1` estimator to the source
transcript and the comparison push-style brief, then record the inputs used.

## KPI table

| KPI | Value | Measurement method | Data source / boundary |
|---|---:|---|---|
| `master_brief_tokens_saved` | _not measured_ | Manual `charclass/v1` comparison of transcript and conventional brief | Manual source artifacts; outside `pcl report kpi` |
| `average_context_pack_tokens` | _not measured_ | `pcl report kpi --json` | `context_pack_generated`; opt-in `--record-usage` runs only |
| `finish_roundtrips_saved` | _not measured_ | Record finish commands and completion-packet outcome during dogfood | `finish` section; unavailable until task 0135 measurement events land |
| `verification_spend_efficiency` | _not measured_ | `executed_pass_rate × execution_rate` from `pcl report kpi --json` | `verification_feedback_stats` over verification feedback and receipt evidence |
| `bound_receipt_coverage` | _not measured_ | Bound-receipt pack count / recorded pack count from `pcl report kpi --json` | `context_pack_generated`; opt-in `--record-usage` runs only |
| `feedback_coverage_rate` | _not measured_ | `pcl report kpi --json` | `verification_feedback_stats` |
| `worker_handoff_success_rate` | _not measured_ | Review resume/packet outcomes after each handoff | `handoff` section plus operator review; unavailable until task 0137 |
| `handoff_confusion_count` | _not measured_ | Count operator-confirmed clarification/retry incidents | Manual dogfood log; do not infer from unrelated events |

## Repository 1 — Project Loop Harness

- Repository / revision:
- Measurement window:
- `pcl report kpi --json` evidence path:
- Manual comparison evidence paths:
- KPI values:
- Missing-data reasons:
- Operator observations:

## Repository 2 — External dogfood repository

- Repository / revision:
- Measurement window:
- `pcl report kpi --json` evidence path:
- Manual comparison evidence paths:
- KPI values:
- Missing-data reasons:
- Operator observations:

## Reproduction checklist

1. Record the repository revision and measurement start date.
2. Use `--record-usage` for every dogfood context-pack generation.
3. Run `pcl report kpi --since <start-date> --json` without mutating project state.
4. Save the JSON output as evidence outside generated dashboard files.
5. Enter `null` together with the emitted `reason` when data is unavailable; do
   not replace missing observations with estimates.
6. Record manual inputs for `master_brief_tokens_saved` and
   `handoff_confusion_count` separately.
