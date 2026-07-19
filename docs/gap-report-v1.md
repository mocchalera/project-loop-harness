# Gap Report v1

`gap-report/v1` records one producer's diagnosis of the earliest failed
handoff in a bounded agent trajectory. It adds a feedback layer above existing
Work Brief, Evidence, approval-provenance, and completion-packet contracts; it
does not create a second harness directory or alter completion semantics.

The design adapts the bounded loop in the Harness Engineering
[Improve One Harnessed Job](https://github.com/lopopolo/harness-engineering/blob/trunk/playbooks/improve-harness.md)
playbook to PLH's existing local state and Evidence model.

## Trust boundary

- A valid report is a producer-authored claim, not a verified fact.
- `earliest_failed_handoff` and `gap_class` remain diagnoses. Shape validation
  does not prove that the producer found the true earliest cause.
- `worker_limitation` is provisional. One trajectory cannot establish a
  general worker limitation.
- A candidate lesson is isolated from project policy until a human-origin
  decision approves promotion against the recorded artifact hash.
- Promotion approval does not apply the lesson. The event always records
  `application_status: pending`; a later authorized task must update the
  named durable owner through its normal workflow and proof boundary.
- PLH never writes AGENTS.md, Skills, tests, APIs, or runbooks automatically
  from a Gap Report.

## Contract fields

Top-level fields are strict; unknown fields fail closed.

- `contract_version`: exactly `gap-report/v1`.
- `producer`: non-empty producer `name` and `version`.
- `generated_at`: RFC 3339 UTC at whole-second precision ending in `Z`.
- `target`: one existing `goal`, `task`, `feature`, `defect`, `workflow_run`,
  or `agent_job` and its PLH ID.
- `related` (optional): a completion `packet_id`, typed `evidence:E-NNNN`
  references, or an existing Workflow Run ID.
- `earliest_failed_handoff`: non-empty `stage` and `description`.
- `gap_class`: one closed value:
  `context`, `capability`, `domain_ownership`, `authority`, `proof`,
  `feedback_delivery`, or `worker_limitation`.
- `candidate_lessons`: zero or more unique `lesson_id` values with the lesson,
  proposed durable owner, and supporting typed Evidence references.

Durable owners are closed to `agents_md`, `skill`, `types`, `api`, `tests`,
`runbook`, `project_docs`, and `tool_error_message`. A new owner or gap class
changes the protected v1 contract and requires schema, validator, fixture,
documentation, and compatibility review.

## Validate and record

Validation is read-only and does not require an initialized project:

```bash
pcl contract validate --type gap-report/v1 gap-report.json --json
```

Recording validates the artifact and all target/related Evidence references
before mutation. `--dry-run` performs the same preflight without writing a
file, Evidence row, target link, event, or outbox record.

```bash
pcl gap add gap-report.json \
  --summary "Release runbook was not discoverable" \
  --dry-run --json

pcl gap add gap-report.json \
  --summary "Release runbook was not discoverable" \
  --json
```

Recorded files use the canonical project-local path
`.project-loop/evidence/gap-reports/e-nnnn-gap-report-v1.json`. The anchor event
stores target, path, byte size, canonical artifact SHA-256, gap class, and
candidate count. The same canonical report cannot be recorded twice.

## Inspect and filter

```bash
pcl gap show --evidence E-0002 --json
pcl gap list --target task:T-0001 --gap-class context --json
```

Read paths require exactly one `gap_report_recorded` anchor and one
`gap_report` target link. They verify the canonical path, reject symlinks and
identity changes, read the recorded byte size once, revalidate the contract,
and compare the canonical SHA-256 with the anchor. Findings remain visible as
`health: warning`; unhealthy reports cannot authorize promotion.

## Approve candidate promotion

Candidate lessons need at least one existing supporting Evidence reference.
Agent and system actors fail with `gap_lesson_human_approval_required`.

The usual path is a conversational or Cockpit decision recorded by an agent:

```bash
pcl gap promote E-0002 \
  --lesson lesson-release-route \
  --actor human:owner \
  --actor-kind human \
  --recorded-by agent:codex \
  --recorder-kind agent \
  --source-kind cockpit \
  --source-ref cockpit:<task-id> \
  --reason "Reviewed the cited Evidence and approved promotion" \
  --json
```

The append-only `gap_lesson_promotion_approved` event binds the human actor,
recorder, source, report Evidence ID/hash, lesson ID/hash, supporting refs,
durable owner, and `application_status: pending`. Repeating the same approval
is idempotent. Changing the report or lesson invalidates the binding.

## Compatibility and scope

This feature keeps DB schema 8. Projects with no Gap Reports behave unchanged.
`completion-packet/v1`, terminal-state rules, dashboard contracts, and legacy
Evidence display semantics are unchanged. The packaged schema is available
through `pcl.contracts.gap_report.gap_report_schema()`.

The AGENTS.md and CLAUDE.md marker blocks are append-once. Fresh initialization
gets the compact operating contract; existing initialized projects are not
silently rewritten and must adopt the new router lines through an explicit,
reviewed instruction update.

Aggregation (`pcl harness review/improve`), automatic owner mutation, causal
claims, telemetry, hosted storage, and external provider calls are outside v1.
