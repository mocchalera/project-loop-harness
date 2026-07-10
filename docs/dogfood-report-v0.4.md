# v0.4 Dogfood KPI Report

This report records the 2026-07-10 v0.4.0 Dogfood Operations measurements for
PLH itself and the external `ax1-moc1` repository. Missing observations remain
explicitly unmeasured; this report does not substitute estimates for absent data.

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

| KPI | Project Loop Harness | ax1-moc1 | Measurement method / boundary |
|---|---:|---:|---|
| `master_brief_tokens_saved` | `null` — no paired push-style brief | `null` — no paired source transcript and push-style brief | Manual `charclass/v1` comparison; inputs were not recorded before these runs |
| `average_context_pack_tokens` | `1698.0` | `3251.0` | One opt-in `context_pack_generated` event per repository |
| `finish_roundtrips_saved` | `null` — `not_yet_measured` | `null` — `not_yet_measured` | The current KPI contract exposes no measured finish baseline for these repositories; no estimate was substituted |
| `verification_spend_efficiency` | `0.3333` | `null` — `no_data_in_window` | `executed_pass_rate × execution_rate` from `verification_feedback_stats` |
| `bound_receipt_coverage` | `0.0` | `0.0` | Neither of the two recorded packs had a bound receipt |
| `feedback_coverage_rate` | `0.6666666666666666` | `null` — `no_data_in_window` | `verification_feedback_stats` |
| `worker_handoff_success_rate` | `1.0` (`3/3`) | `null` — no packet-based worker handoff run | Manual operator review of the 0135, 0136, and 0137 Cockpit worker handoffs; not inferred from unrelated events |
| `handoff_confusion_count` | `0` | `null` — no packet-based worker handoff run | Operator-confirmed semantic clarification/retry incidents only |

## Repository 1 — Project Loop Harness

- Repository / revision: `/Users/mocchalera/Dev/project-loop-harness` at
  `34ac60c` (the working tree also contained unrelated pre-existing local state).
- Measurement window: all locally recorded data through 2026-07-10; one explicit
  opt-in context pack was recorded during this dogfood pass.
- `pcl report kpi --json` evidence path:
  `.project-loop/reports/g-0008-plh-kpi.json`.
- Manual comparison evidence paths: none; therefore
  `master_brief_tokens_saved` is `null` rather than estimated.
- KPI values: average context pack `1698.0`; bound receipt coverage `0.0`;
  verification spend efficiency `0.3333`; feedback coverage
  `0.6666666666666666`.
- Missing-data reasons: finish metrics are `not_yet_measured`; no paired brief
  exists for the manual token-saving comparison.
- Operator observations: the opt-in pack targeted completed task `T-0023` and
  remained within its token budget. The three implementation handoffs for
  0135–0137 were independently reviewed, integrated, and passed the parent full
  suite, producing a manual worker-handoff result of `3/3` with no confirmed
  handoff-semantics confusion.

## Repository 2 — External dogfood repository

- Repository / revision: `/Users/mocchalera/Dev/ax1-moc1`; revision unavailable
  because the directory is not a Git repository.
- Measurement window: all locally recorded data through 2026-07-10; one explicit
  opt-in context pack was recorded during this dogfood pass.
- `pcl report kpi --json` evidence path:
  `.project-loop/reports/g-0008-ax1-moc1-kpi.json` in the PLH repository.
- Manual comparison evidence paths: none; therefore
  `master_brief_tokens_saved` is `null` rather than estimated.
- KPI values: average context pack `3251.0`; bound receipt coverage `0.0`.
- Missing-data reasons: verification feedback is `no_data_in_window`; finish is
  `not_yet_measured`; no packet-based resume handoff or paired manual token input
  was recorded.
- Operator observations: the Project Loop database was migrated from schema 5
  to schema 8 after explicit approval. The pre-migration DB and JSONL audit log
  are backed up under
  `/Users/mocchalera/.agi-tools/backups/ax1-moc1-pcl-pre-migration-20260710T1830JST/`.
  Strict validation passed after migration. The measured pack targeted existing
  passed job `J-0001` and remained within its token budget.

## Reproduction checklist

1. Record the repository revision when available and the measurement date.
2. Use `--record-usage` for every dogfood context-pack generation.
3. Run `pcl report kpi --since <start-date> --json` without mutating project state.
4. Save the JSON output as evidence outside generated dashboard files.
5. Enter `null` together with the emitted `reason` when data is unavailable; do
   not replace missing observations with estimates.
6. Record manual inputs for `master_brief_tokens_saved` and
   `handoff_confusion_count` separately.

## Commands used for this measurement

```bash
PYTHONPATH=src python -m pcl --root /Users/mocchalera/Dev/project-loop-harness context pack --task T-0023 --record-usage --json
PYTHONPATH=src python -m pcl --root /Users/mocchalera/Dev/ax1-moc1 context pack --job J-0001 --record-usage --json
PYTHONPATH=src python -m pcl --root /Users/mocchalera/Dev/project-loop-harness report kpi --json
PYTHONPATH=src python -m pcl --root /Users/mocchalera/Dev/ax1-moc1 report kpi --json
```
