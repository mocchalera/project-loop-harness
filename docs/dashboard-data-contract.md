# Dashboard Data Contract

`pcl render` writes `.project-loop/dashboard/dashboard-data.json` with this contract:

```text
dashboard-data/v1
```

The JSON file is a deterministic review artifact derived from SQLite state, JSONL events, reports, and workflow templates. It is not the source of truth and must not be edited directly. When an agent needs rendered dashboard context, use this JSON contract instead of reading or parsing `dashboard.html`.

## Top-Level Keys

The top-level object must contain:

- `contract_version`
- `generated_at`
- `source_db`
- `validation`
- `next_action`
- `risk_summary`
- `counts`
- `current_goal`
- `active_workflow`
- `active_agent_jobs`
- `features`
- `user_stories`
- `test_cases`
- `defects`
- `goals`
- `workflow_runs`
- `workflow_proposals`
- `agent_jobs`
- `verifications`
- `decisions`
- `escalations`
- `evidence`
- `recent_events`
- `reports`

## Required Nested Keys

`validation`:

- `ok`
- `errors`
- `warnings`

`next_action`:

- `type`
- `command`
- `reason`
- `priority`
- `blocking`
- `requires_human`
- `safe_to_run`
- `run_policy`
- `human_guidance`
- `expected_after`
- `target`

`risk_summary`:

- `blocking`
- `highest_severity`
- `items`

`risk_summary.items` rows:

- `type`
- `severity`
- `blocking`
- `requires_human`
- `summary`
- `command`
- `target`
- `count`

`risk_summary.items[].target`:

- `type`
- `id`

`counts`:

- `features`
- `user_stories`
- `test_cases`
- `open_defects`
- `goals`
- `open_decisions`
- `workflow_runs`
- `queued_jobs`
- `open_escalations`
- `workflow_proposals`

`workflow_proposals` rows:

- `id`
- `workflow_id`
- `path`
- `workflow_path`
- `status`
- `summary`
- `review_summary`
- `created_at`
- `reviewed_at`
- `content_sha256`
- `parse_error`
- `data`

`user_stories` rows:

- `id`
- `feature_id`
- `actor`
- `goal`
- `benefit`
- `expected_behavior`
- `status`
- `updated_at`

`test_cases` rows:

- `id`
- `feature_id`
- `story_id`
- `type`
- `scenario`
- `expected`
- `status`
- `last_run_id`
- `evidence_id`
- `updated_at`

`current_goal`, when present:

- `id`
- `title`
- `status`
- `completion_json`
- `budget_json`
- `updated_at`

`active_workflow`, when present:

- `id`
- `workflow_id`
- `goal_id`
- `status`
- `iteration`
- `started_at`
- `summary`
- `budget`

`active_agent_jobs` and `agent_jobs` rows:

- `id`
- `workflow_run_id`
- `role`
- `status`
- `prompt_path`
- `output_path`
- `summary`
- `evidence_ids`
- `evidence`
- `latest_evidence_id`
- `latest_evidence_path`

`verifications` rows:

- `id`
- `workflow_run_id`
- `target_job_id`
- `target_job_evidence_ids`
- `workflow_report_path`
- `verifier_role`
- `result`
- `reasons_json`
- `created_at`

`evidence` rows:

- `id`
- `type`
- `path`
- `related_agent_job_ids`
- `related_workflow_run_ids`
- `related_report_paths`
- `command`
- `summary`
- `created_at`

`recent_events` rows:

- `id`
- `event_type`
- `entity_type`
- `entity_id`
- `created_at`

`reports` rows:

- `name`
- `path`
- `related_evidence_ids`
- `related_agent_job_ids`
- `related_workflow_run_ids`

## HTML Navigation

Dashboard HTML should expose deterministic row anchors for rows that have an `id`, using `row-<id>`.

Entity references such as `J-0001`, `E-0001`, `WR-0001`, and `V-0001` should render as in-page links when they appear in navigation columns. Path values should render as file links. This keeps the dashboard static while still allowing review navigation across jobs, evidence, reports, and verifications.

The "Risk & Blockers" panel renders `risk_summary` near the top of the dashboard. It is a derived review aid only: it summarizes validation issues, human queues, active defects, failed or blocked workflow runs, and failed or blocked agent jobs from existing state. It must not be treated as source of truth.

## Compatibility

Adding a top-level key or changing required keys is a contract change and should be tested deliberately. Rendering must remain deterministic for unchanged state, and dashboard rendering must not require strict validation to pass.
