# 0140: KPI post-integration data sources

- **Status:** Approved release blocker
- **Milestone:** v0.4.0 release candidate
- **Priority:** P0
- **Estimated size:** S
- **Dependencies:** 0135 and 0137 merged

## Problem

`pcl report kpi` still labels finish and handoff metrics with
`not_available_until_task_0135` and `not_available_until_task_0137` after both
tasks have shipped. The wording is stale. Some finish metrics can now be derived
from durable `completion_packet_created` events, while `pcl resume` intentionally
remains read-only and records no execution event.

## Goal

Report the post-integration measurement truth without inventing data:

- derive finish execution count and packet outcome distribution from
  `completion_packet_created` events;
- keep manually measured round-trip savings explicitly unavailable until a
  comparison is recorded;
- explain that resume and handoff generation counts are unavailable because the
  read-only operation is not recorded.

## Scope

1. Query `completion_packet_created` events using the existing `--since` window.
2. Return `finish_execution_count` as the event count and
   `packet_outcome_distribution` as deterministic outcome counts.
3. Return `null` plus `no_data_in_window` for the distribution when no finish
   event exists in the selected window.
4. Return `finish_roundtrips_saved: null` with
   `manual_comparison_not_recorded` and a factual manual-comparison data source.
5. Return both handoff metrics as `null` with
   `read_only_operation_not_recorded` and a factual `pcl resume` data source.
6. Update the stable empty fixture and add event/window regression coverage.

## Invariants

- `pcl report kpi` remains fully read-only.
- `kpi-report/v1` section and metric names remain unchanged.
- No resume telemetry, schema migration, dependency, external transmission, or
  fabricated estimate is introduced.
- Malformed recorded event payloads fail explicitly instead of being skipped.

## Acceptance criteria

- Empty repositories report finish count `0`, no-data distribution, manual
  round-trip reason, and read-only handoff reasons without stale task IDs.
- Multiple completion events produce a deterministic outcome distribution.
- `--since` excludes older completion events.
- DB size/counts and JSONL bytes remain unchanged by the report.
- Targeted KPI tests, ruff, and the full test suite pass.

