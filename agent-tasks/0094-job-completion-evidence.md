# Task 0094: Job Completion Evidence Linkage (v0.2.2, F3)

Design source: `docs/evidence-entry-paths-design.md`
(**APPROVED 2026-07-07**, Part 3). Depends on 0093 being merged (its
adhoc evidence rows are natural inputs here, and both touch cli.py /
validators tests). No migration; schema stays v5.

## Goal

In the ax1-moc1 dogfood run, `pcl jobs list --json` showed empty
evidence for jobs whose `output_path` files existed, and there was no
way to attach evidence when completing a job. Close both gaps using
the EXISTING `latest_evidence_id` pointer on agent jobs.

## Scope

### 1. `pcl jobs complete <job-id> --evidence E-00xx`

- Optional repeatable? NO — single `--evidence` flag (the
  one-pointer model matches `latest_evidence_id`; multiple artifacts
  are one adhoc bundle from 0093).
- The referenced evidence row must exist → typed error otherwise,
  nothing changed.
- Sets `latest_evidence_id` on the job as part of the existing
  completion flow; completion event payload gains the evidence id.
  All existing completion semantics (summary, status transition,
  guards) unchanged.

### 2. Jobs-list evidence visibility audit (the ax1-moc1 symptom)

- Reproduce first: in the ax1-moc1 run, jobs completed through the
  normal flow showed `evidence: []`/empty in `pcl jobs list --json`
  even though `output_path` existed and ingest had run. Find out
  why (linkage never set? read path not surfacing it? ingest path
  only sets it on certain flows?) and fix the actual cause — do not
  paper over it in the list renderer.
- After the fix: a job whose output was ingested surfaces its
  evidence reference in `jobs read` / `jobs list --json` and
  dashboard-data.

### 3. Documentation

- `docs/golden-path.md` / agent adapter docs: one short paragraph —
  complete a job with `--evidence` when the artifact is already
  recorded (0093 flow), otherwise ingest output as before.

## Acceptance Criteria

- `jobs complete --evidence E-00xx` sets `latest_evidence_id`,
  appends the completion event with the evidence id, and the linkage
  appears in `jobs read --json`, `jobs list --json`, and
  dashboard-data.
- Unknown evidence id → typed error; job stays incomplete and
  unchanged.
- Root-cause test for the visibility bug: a test that reproduces the
  original empty-evidence symptom path and asserts it is fixed
  (write the test against the actual discovered cause, and explain
  the cause in the task report).
- Existing completion without `--evidence` behaves exactly as
  before.
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes; strict validate/audit integrity
  regression stays green.

## Do Not

- Do not add repeatable `--evidence` or an M:N link table.
- Do not auto-create evidence from `output_path` without ingest —
  linkage requires a real evidence row.
- Do not change ingest contracts (`agent-output/v1`) or job state
  machine semantics.
