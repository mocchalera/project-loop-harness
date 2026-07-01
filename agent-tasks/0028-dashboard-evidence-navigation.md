# Task 0028: Dashboard Evidence Navigation

## Goal

Make the dashboard easier to review by connecting jobs, evidence, reports, and verifications without changing the source of truth.

The dashboard now has a stable data contract. The next step is to use that contract to expose navigation metadata and deterministic HTML links so a human can trace:

```text
agent job -> evidence -> report -> verification
```

## Scope

- Add derived navigation fields to dashboard data:
  - evidence rows expose related agent jobs, workflow runs, and reports;
  - report rows expose related evidence, agent jobs, and workflow runs;
  - verification rows expose target job evidence and workflow report path.
- Keep the existing `dashboard-data/v1` top-level keys unchanged.
- Render deterministic in-page anchors for rows with IDs.
- Render entity ID references as in-page links where possible.
- Render path references as file links where possible.
- Add regression tests for JSON navigation fields and generated HTML anchors/links.
- Document the navigation fields in the dashboard data contract.

## Acceptance criteria

- `pcl render` links job evidence IDs to evidence rows in dashboard HTML.
- Evidence rows include `related_agent_job_ids`, `related_workflow_run_ids`, and `related_report_paths`.
- Report rows include `related_evidence_ids`, `related_agent_job_ids`, and `related_workflow_run_ids`.
- Verification rows include `target_job_evidence_ids` and `workflow_report_path`.
- Dashboard data remains deterministic for unchanged state.
- No schema migration is added.
- No dependency is added.

## Do not

- Do not edit generated dashboard HTML directly.
- Do not add JavaScript or frontend frameworks.
- Do not make dashboard data the source of truth.
- Do not make rendering depend on strict validation.
