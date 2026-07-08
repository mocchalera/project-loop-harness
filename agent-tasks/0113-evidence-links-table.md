# 0113: Generic evidence links table (migration 007)

Milestone: v0.3.0 Target-Bound Context
Priority: P1
Area: schema/evidence
Origin: docs/growth-plan-v0.2.4-v0.5.md v0.3.0; third-party review 議題1 — migration
approved and 0108 no-migration invariant retracted (Sakamoto approved 2026-07-08).

## Problem

Evidence-to-target linkage is currently a single `evidence.linked_task_id`
column (migration 006), which can only express "supporting evidence for a
task". v0.3.0 introduces a second link role — a code-context receipt bound
to a task or job (0108) — and v0.3.2 will add master-trace / intent-index
roles. A single typed column cannot express a role, and adding one column per
target type (`linked_job_id`, `linked_goal_id`, and so on) sprawls.

Introduce a generic, queryable `evidence_links` table so target-bound receipt
selection (0108), `pcl context check` (v0.3.1), and v0.4 coverage KPIs become
SQL queries rather than artifact scans. This is a control-plane primitive, not
a per-feature column.

## Scope

1. Add migration `007_evidence_links.sql`:
   ```sql
   PRAGMA foreign_keys = ON;

   CREATE TABLE IF NOT EXISTS evidence_links (
     evidence_id TEXT NOT NULL REFERENCES evidence(id),
     target_type TEXT NOT NULL,
     target_id   TEXT NOT NULL,
     link_role   TEXT NOT NULL,
     created_at  TEXT NOT NULL,
     PRIMARY KEY (evidence_id, target_type, target_id, link_role)
   );

   CREATE INDEX IF NOT EXISTS idx_evidence_links_target
     ON evidence_links(target_type, target_id, link_role, created_at);

   -- Backfill existing task-linked evidence as role 'supporting'.
   INSERT OR IGNORE INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at)
   SELECT id, 'task', linked_task_id, 'supporting', created_at
   FROM evidence
   WHERE linked_task_id IS NOT NULL;
   ```
   Vocabulary in use now: `target_type` is `task` or `agent_job`;
   `link_role` is `supporting` or `code_context`. Reserve (do not emit yet)
   `goal` / `workflow_run` / `decision` / `escalation` and
   `master_trace` / `intent_index` / `worker_output`.
2. Write path: `pcl evidence add --task T-XXXX` (evidence.py) keeps setting the
   `evidence.linked_task_id` column (0.x compat) and also inserts an
   `evidence_links` row `(evidence_id, 'task', task_id, 'supporting', now)` in
   the same transaction, before the existing `append_event`.
3. Read path: `context.py._linked_task_evidence` selects from `evidence_links`
   where `target_type='task' AND link_role='supporting'`, joined to `evidence`
   for the display columns, ordered `created_at, evidence_id`. When the
   `evidence_links` table is absent (pre-migration DB opened by a newer binary
   mid-upgrade), fall back to the current `linked_task_id` column query. Output
   shape, ordering, and member/stored-path resolution are unchanged.
4. Strict validation (`validators.py`): add a dangling-link check modeled on the
   verification `receipt_evidence_id` check (validators.py:596) — every
   `evidence_links.evidence_id` must resolve to an existing evidence row (the
   existing `PRAGMA foreign_key_check` already covers this; keep an explicit,
   message-consistent check too), and for known target types the `target_id`
   must exist (`task` maps to `tasks`, `agent_job` maps to `agent_jobs`).
   Unknown `target_type` values are tolerated with no error (forward
   compatibility).
5. Provide two small internal helpers for 0108 to reuse (no new CLI surface):
   insert a link row, and select the newest `evidence_id` for a given
   `(target_type, target_id, link_role)`.

## Invariants (what to protect, on the normal paths)

- The canonical write path for a task-linked ad-hoc evidence is, in one
  transaction: the `evidence` row plus the `linked_task_id` column plus the
  `evidence_links` row plus the `adhoc_evidence_recorded` event. Do not drop the
  `linked_task_id` column write (compat). Do not write an `evidence_links` row
  without its mirroring `evidence` row.
- The migration backfill is idempotent (`INSERT OR IGNORE`) and additive: it
  must not update or delete any `evidence` row, and re-running `pcl migrate`
  must be a no-op.
- `evidence_links` is written only through `pcl` (evidence add today, 0108
  tomorrow). No command deletes links in this task; no raw-SQL mutation path.
- The existing task context-pack `linked_evidence` output — shape, ordering,
  member/stored paths — is unchanged for existing DBs after backfill.
- Additive only: no existing table or column is dropped or repurposed. Schema
  version advances 6 to 7; `never-downgrade` and DB-ahead typed rejection (0076)
  continue to hold.

## Non-scope

- `pcl evidence link` / `unlink` CLI verbs (links are written implicitly by
  `evidence add` and, in 0108, by `impact --for-task/--for-job`).
- Job / goal / decision linking commands beyond the helper 0108 needs.
- Dashboard changes. The existing `heading_evidence_links` locale string is an
  unrelated UI heading, not this table.
- Removing or deprecating `linked_task_id` (deferred past 0.x).
- Reading `evidence_links` from the code-context receipt selection path (that is
  0108).

## Acceptance

- Fresh `pcl init` gives schema v7, `evidence_links` present,
  `pcl validate --strict --json` green.
- A v6 to v7 live migration backfills every `linked_task_id` row into
  `evidence_links` as role `supporting`; backfilled row count equals the number
  of non-null `linked_task_id` rows; a second `pcl migrate` changes nothing.
- `pcl evidence add --task T-0001` writes both the column and the
  `evidence_links` row; the task context pack lists the evidence identically to
  before.
- A hand-broken dangling link (an `evidence_links` row whose `target_type='task'`
  `target_id` has no matching task) is reported by `validate --strict`; a row
  with an unknown `target_type` is tolerated (no error).
- An older (v6-aware) `pcl` binary typed-rejects a v7 DB with
  `schema_version_ahead` (0076 behavior preserved).
- Full `pytest` green; live smoke in a scratch project (`init`, then `evidence
  add --task`, then `validate --strict`, then context pack).
