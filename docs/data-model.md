# Data Model

## Tables

The database is created and upgraded through ordered SQL migrations in
`src/pcl/db/migrations/`. `src/pcl/db/schema.sql` is the base v1 schema, while
new installs currently apply migrations through schema version 8.

Core tables:

- `metadata`
- `schema_migrations`
- `events`
- `outbox_records`
- `goals`
- `workflows`
- `workflow_runs`
- `agent_jobs`
- `agents`
- `features`
- `user_stories`
- `test_cases`
- `tasks`
- `task_dependencies`
- `defects`
- `decisions`
- `evidence`
- `verifications`
- `escalations`
- `code_index_runs`
- `code_index_files`
- `verification_feedback`

## Entity relationships

```text
Goal
  └─ WorkflowRun
      ├─ AgentJob
      └─ Verification

Agent
  └─ AgentJob lease assignment

Feature
  ├─ UserStory
  ├─ TestCase
  └─ Defect

Task
  ├─ Goal?
  ├─ Feature?
  ├─ Defect?
  ├─ Task dependencies
  └─ Linked Evidence?

Defect
  ├─ TestCase?
  ├─ Evidence?
  └─ Verification via WorkflowRun

Decision / Escalation
  └─ blocks Goal, Feature, Defect, or WorkflowRun through JSON references

CodeIndexRun
  └─ CodeIndexFile

ContextReceiptEvidence
  └─ VerificationFeedback

Event
  └─ OutboxRecord (JSONL projection delivery state)
```

Schema version 8 gives every event a positive, unique, contiguous `sequence`
and adds the retained `outbox_records` delivery ledger. Domain state, the event,
and its pending outbox row commit together. `events.jsonl` is updated only after
that commit and is considered durable only after file `fsync` succeeds.

## ID prefixes

| Entity | Prefix | Example |
|---|---|---|
| Goal | G | G-0001 |
| Feature | F | F-0001 |
| User Story | US | US-0001 |
| Test Case | TC | TC-0001 |
| Task | T | T-0001 |
| Defect | D | D-0001 |
| Workflow Run | WR | WR-0001 |
| Agent Job | J | J-0001 |
| Agent | A | A-0001 |
| Evidence | E | E-0001 |
| Verification | V | V-0001 |
| Escalation | ESC | ESC-0001 |
| Decision | DEC | DEC-0001 |
| Code Index Run | CI | CI-0001 |
| Verification Feedback | VF | VF-0001 |
| Event | EV | EV-... |

Prefixed IDs allocated through `next_prefixed_id` are serialized with a SQLite
`BEGIN IMMEDIATE` transaction. The service layer starts the transaction before
reading the current maximum ID, holds the write lock while inserting the row,
then releases it on commit or rollback. Concurrent local `pcl` writers therefore
wait and receive distinct human-readable IDs instead of racing on the same
`<prefix>-NNNN` value. If SQLite cannot acquire the write lock within the local
busy timeout, the command fails before allocating an ID; callers must not leave
partial evidence artifacts or events for that failed attempt.

## Status design principles

- Status must be constrained.
- Transitions must append an event.
- Closing a defect must require evidence or waiver.
- Dashboard status is derived, not manually set.

## Lifecycle transitions

The CLI/runtime owns lifecycle transitions for agent jobs, workflow runs,
verifications, goals, defects, stories, test cases, and tasks. Commands must
reject invalid jumps instead of letting agents assign arbitrary status values.

Current implemented examples:

```text
agent_job.queued|running|blocked -> passed|failed|cancelled
workflow_run.queued|running|blocked -> passed|failed|cancelled
goal.open|active|blocked -> closed|cancelled
defect.open -> triaged -> in_progress -> fixed -> verified -> closed
defect.open|triaged|in_progress|fixed|verified -> waived
user_story.draft -> review -> approved|waived
test_case.planned -> passing|failing|blocked|missing|waived
task.todo|ready|in_progress|blocked|done|cancelled|waived -> any other task status with reason
```

## Agent Registry And Leases

Schema version 3 adds an `agents` registry and lease fields on `agent_jobs`.
Agents are durable local records with `name`, `role`, `adapter`,
`max_concurrency`, `status`, and normalized `metadata_json`.

Agent status is constrained to:

```text
agent.active|paused -> active|paused
agent.active|paused -> retired through `pcl agent retire`
```

Agent job status values are unchanged. Lease state is additive:

- `assigned_agent_id` optionally points at `agents.id`.
- `lease_expires_at` records the current lease deadline.
- `last_heartbeat_at` records the latest heartbeat command time.
- `attempts` counts expired lease reaps.

An active lease is a job with `status = 'running'`, `assigned_agent_id` set,
and `lease_expires_at` greater than the current UTC timestamp. Lease expiry is
evaluated lazily by commands; no background process mutates state. The only
command that mutates expired leases is `pcl jobs reap`.

`loop.lease_ttl_seconds` defaults to `1800`. `loop.max_lease_attempts` defaults
to `2` and means total expired lease attempts before blocking: the first expiry
is requeued, and the second expiry blocks the job and opens a high-severity
escalation.

Completing a workflow run requires all jobs to pass and an approved
verification. Closing a goal requires explicit evidence text or an approved
verification. Fixing, closing, or waiving a defect records evidence, and
verifying a defect requires an approved verification tied to the defect repair
workflow run.

## Code Context Index

Schema version 4 adds the approved explainable code context index:

- `code_index_runs`: `id`, `root_path`, `created_at`, `git_head`,
  `file_count`, `indexed_bytes`, `ignored_count`, `index_version`, `status`,
  `summary_json`.
- `code_index_files`: `id`, `index_run_id`, `path`, `language`, `size_bytes`,
  `mtime`, `sha256`, `line_count`, `symbol_summary_json`, `test_hint_json`.

The index is an explicit snapshot. The working tree remains the source of
truth, and status/impact commands report staleness when the snapshot differs
from current file metadata or Git HEAD.

Ignored paths, hash-skip reasons for binary/large files, and language counts
live in `code_index_runs.summary_json`. File-level symbol-lite and test-hint
metadata live in JSON columns on `code_index_files`.

Impact receipts are not a new table. `pcl impact --diff` writes a JSON artifact
under `.project-loop/evidence/context-receipts/` and registers it through the
existing `evidence` table with type `context_receipt`, plus an append-only
event.

## Adhoc Evidence Manifests

`pcl evidence add` records existing local files that were produced outside the
agent-job ingest path. One `--file` creates evidence type `adhoc_artifact`; two
or more `--file` flags create `adhoc_bundle`.

The command writes an `adhoc-evidence/v0` manifest under
`.project-loop/evidence/adhoc/` and stores one `evidence` row whose `path`
points at that manifest. By default, manifest members are referenced in place
and pinned at record time with:

- relative `path`;
- `path_scope` (`in_project` or `outside_project`, omitted by older manifests);
- `size_bytes`;
- `sha256`.

Member files are not copied and their contents are never embedded in the
manifest. The optional `--command` value is the caller's claim about how the
artifact was produced. PLH stores it verbatim on the evidence row; it does not
run the command or verify that the command produced the files.

`pcl evidence show E-XXXX [--json]` resolves the stable row metadata without
changing state: ID, type, summary, caller-claimed command, recorded path, and
creation time. For supported `adhoc-evidence/v0` manifests it additionally
returns member paths, copied stored paths, and recorded hashes. It never inlines
member contents or executes the claimed command. Unknown and malformed IDs are
typed input errors.

Schema version 6 adds `evidence.linked_task_id`, a nullable reference to
`tasks.id`. `pcl evidence add --task T-XXXX` sets that column only when the
task already exists. Unknown or invalid task ids are rejected before manifest
creation, file copies, evidence rows, or events. Unlinked adhoc evidence keeps
the same row shape as before except for the nullable column.

`pcl evidence add --copy` is opt-in local durability. After path-scope and
sensitive-filename guards pass, PLH copies each member to
`.project-loop/evidence/adhoc-files/<evidence-id>/<NN>-<basename>`, re-hashes
the copy, and records member-level:

- `storage_mode: "copied"`;
- `stored_path`.

For copied members, PLH asserts only that at record time it wrote a
byte-identical copy (same `sha256`) of the file the caller named to
`stored_path`. The copy is durable only in the local sense that it survives
workspace cleanup on this machine; `.project-loop/evidence/` remains local
state and is not a transfer bundle.

The project config key `evidence.copy_max_member_bytes` controls the maximum
per-member size for `--copy`; it defaults to 10 MB. Members over the cap are
rejected before any evidence row or event is written. Members over half the cap
are recorded with a `large_evidence_member` warning. Reference mode is not
affected by the copy cap.

Strict validation treats a missing or corrupt adhoc manifest as a state
integrity error. If a referenced member file is later deleted or edited, strict
validation reports a warning naming the evidence id, member path, and drift kind
while keeping the recorded hash as the pinned claim.

For copied members, the stored copy is the reviewable artifact. A missing or
changed copy is a warning. Original source churn is informational in health
surfaces and does not make strict validation warn when the copy remains intact.

Worked example:

```bash
pcl evidence add \
  --file work/reports/pytest-out.txt \
  --summary "pytest run for suggestion E-0017/VS-01" \
  --command "python3 -m pytest tests/test_context.py" \
  --copy \
  --json
pcl verification feedback --suggestion E-0017/VS-01 --status executed --result passed --evidence E-00xx
```

## Verification Feedback

Schema version 5 adds `verification_feedback`, an append-only event table for
caller feedback about context receipt suggestions:

```sql
CREATE TABLE IF NOT EXISTS verification_feedback (
  id TEXT PRIMARY KEY,
  suggestion_id TEXT NOT NULL,
  receipt_evidence_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('executed', 'skipped', 'not_applicable')),
  result TEXT CHECK(result IN ('passed', 'failed', 'inconclusive')),
  supporting_evidence_id TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  CHECK(
    (status = 'executed' AND result IS NOT NULL AND supporting_evidence_id IS NOT NULL)
    OR (status != 'executed' AND result IS NULL)
  ),
  FOREIGN KEY(receipt_evidence_id) REFERENCES evidence(id),
  FOREIGN KEY(supporting_evidence_id) REFERENCES evidence(id)
);
```

There is deliberately no `UNIQUE(suggestion_id)`: multiple feedback rows for one
suggestion are legal. Commands append a new row and a JSONL event rather than
rewriting prior feedback.

`receipt_evidence_id` points to the `context_receipt` evidence row named by the
suggestion ID prefix, such as `E-0001` in `E-0001/VS-01`.
`supporting_evidence_id` points to an evidence row backing the caller's claim
when one is supplied; it is required for `executed`.

Receipts and summaries do not store feedback status. Displays derive "no
feedback recorded" at read time when a suggestion has zero feedback rows, and
derive the latest feedback from row order when multiple rows exist.
