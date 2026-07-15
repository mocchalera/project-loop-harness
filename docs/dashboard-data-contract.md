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
- `checkpoint`
- `human_decisions`
- `risk_summary`
- `counts`
- `current_goal`
- `active_workflow`
- `active_agent_jobs`
- `features`
- `user_stories`
- `test_cases`
- `defects`
- `tasks`
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

`checkpoint`:

- `ok`
- `checkpoint_recommended`
- `checkpoint_requires_human`
- `mode`
- `threshold`
- `threshold_reached`
- `completed_features_since_checkpoint`
- `completed_feature_ids_since_checkpoint`
- `passed_workflow_runs_since_checkpoint`
- `feature_status_counts`
- `open_goal_count`
- `latest_checkpoint`
- `git`

The default `mode` is `advisory`. An advisory recommendation may appear as a
non-blocking `checkpoint_advisory` item in `risk_summary.items`, but it is not
included in `human_decisions` and does not replace normal `next_action` routing.
Only `mode: blocking` sets `checkpoint_requires_human` and routes the legacy
human-gated `checkpoint_review` action.

When `next_action.requires_human` is true, `next_action` may also include the
same cockpit fields used by `human_decisions.items`:

- `why_blocked`
- `options`
- `recommendation`
- `recommendation_reason`
- `related_evidence_paths`
- `receipt_paths`

`human_decisions`:

- `count`
- `items`

All `human_decisions.items` rows include additive human-decision cockpit fields:

- `why_blocked`
- `options`
- `recommendation`
- `recommendation_reason`
- `related_evidence_paths`
- `receipt_paths`

`human_decisions.items[].options` rows:

- `label`
- `command`
- `why_safe`
- `risk_if_run`

`receipt_paths` is optional receipt metadata. It may be absent or empty until a
receipt indexing feature exists; dashboard rendering must not depend on receipt
discovery.

`human_decisions.items` rows for open decisions:

- `kind`
- `id`
- `question`
- `recommendation`
- `created_at`
- `resolve_command`
- `linked_escalation_ids`

`human_decisions.items` rows for open escalations:

- `kind`
- `id`
- `severity`
- `question`
- `recommendation`
- `created_at`
- `resolve_command`
- `linked_decision_ids`

`human_decisions.items` rows for active `needs_human` verifications:

- `kind`
- `id`
- `workflow_run_id`
- `reasons`
- `created_at`
- `resolve_command`

`human_decisions.items` rows for human-required next actions:

- `kind`
- `type`
- `command`
- `reason`

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

`features` rows:

- `id`
- `name`
- `surface`
- `status`
- `confidence`
- `updated_at`

`defects` rows:

- `id`
- `feature_id`
- `severity`
- `status`
- `expected`
- `actual`
- `updated_at`

`tasks` rows:

- `id`
- `title`
- `status`
- `priority`
- `owner`
- `risk`
- `effort`
- `related_goal_id`
- `related_feature_id`
- `related_defect_id`
- `dependency_ids`
- `dependent_ids`
- `created_at`
- `updated_at`

`goals` rows:

- `id`
- `title`
- `status`
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

`workflow_runs` rows:

- `id`
- `workflow_id`
- `goal_id`
- `status`
- `iteration`
- `started_at`
- `summary`

`active_agent_jobs` and `agent_jobs` rows:

- `id`
- `workflow_run_id`
- `role`
- `status`
- `assigned_agent_id`
- `attempts`
- `lease_expires_at`
- `last_heartbeat_at`
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

`decisions` rows:

- `id`
- `status`
- `question`
- `recommendation`
- `selected_option`
- `reason`
- `blocks_json`
- `created_at`
- `linked_escalation_ids`

`escalations` rows:

- `id`
- `workflow_run_id`
- `severity`
- `question`
- `recommendation`
- `status`
- `created_at`
- `linked_decision_ids`

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

The "Needs Your Decision" panel renders `human_decisions` immediately after the
validation/risk/next-action block. It is the consolidated export surface for
human decision notifications. It includes enough ids, prompt text,
why-blocked text, recommendations, options, links, and commands for a consumer
to render each item without joining against other dashboard sections.

Decision options are informational command rows in the generated static HTML.
Approve, reject, hold, and request-more-evidence choices must be rendered with
equal visual weight; the dashboard must not create interactive buttons that run
commands.

Dashboard HTML chrome can be localized with `pcl render --locale ja` or
`dashboard.locale: "ja"` in `pcl.yaml`. Locale selection affects only
`dashboard.html`; `dashboard-data.json` keys and values remain English and
locale-independent.

## Compatibility

Adding a top-level key or changing required keys is a contract change and should be tested deliberately. Rendering must remain deterministic for unchanged state, and dashboard rendering must not require strict validation to pass.
