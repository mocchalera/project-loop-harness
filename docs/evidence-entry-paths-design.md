# v0.2.2 Design: Evidence Entry Paths

Status: **DRAFT — pending human approval.** No implementation before
approval. No migration is proposed; everything here stays on schema
v5.

Sources: v0.2.0 plan M2 dogfood finding (ad-hoc executed feedback has
no evidence path) and ax1-moc1 external-project agent feedback items
F2 (single-string `--evidence`), F3 (job completion evidence), F6
(evidence bundle for screenshot + viewport + visual-check). These are
four surfaces of ONE gap: **operators and agents produce reviewable
artifacts outside the job loop, and PLH has no honest way to accept
them as evidence.**

## Design principles (unchanged)

- Evidence rows are claims with pointers: PLH records that an
  artifact existed with a given hash at record time. It never claims
  the artifact is correct or that PLH observed its production.
- CLI-only mutation; every insert goes through the service layer and
  appends a standard event (SQLite + JSONL via `append_event`).
- No fabrication: PLH never generates artifact content on the
  caller's behalf.

## Part 1: `pcl evidence add` (the missing primitive)

```bash
pcl evidence add --file work/reports/pytest-out.txt \
  --summary "pytest run for suggestion E-0017/VS-01" \
  --command "python3 -m pytest tests/test_context.py" --json
```

- Requires at least one existing, readable `--file`; records path,
  size, and sha256 AT RECORD TIME into a small manifest artifact
  under `.project-loop/evidence/adhoc/`, creates one evidence row
  pointing at that manifest, and appends one event.
- Evidence `type` is `adhoc_artifact` — the epistemic marker that
  this entered outside the job/workflow loop. Reports, dashboards,
  and strict validation treat it as normal evidence; the type makes
  provenance visible, not second-class.
- `--command` is the CALLER'S statement of how the artifact was
  produced. PLH stores it verbatim as a claim; it does not run or
  verify it (same discipline as `verification_feedback.executed`).
- This closes the M2 dogfood gap directly:
  `pcl evidence add --file out.txt ...` → `E-00xx` →
  `pcl verification feedback --suggestion 'E-0017/VS-01'
  --status executed --result passed --evidence E-00xx`.
- The earlier `--output-file` idea on `verification feedback` is
  SUPERSEDED by this: one general primitive instead of a per-command
  attachment flag.

## Part 2: bundles — multiple files, ONE evidence row (F2 + F6)

`--file` is repeatable. Two or more files produce a single evidence
row of type `adhoc_bundle` whose manifest lists every member with
path, size, and sha256:

```bash
pcl evidence add \
  --file work/reports/rendered-desktop.png \
  --file work/reports/rendered-mobile.png \
  --file work/reports/visual-check.json \
  --summary "visual QA bundle for TC-0002"
```

- Members are referenced in place and pinned by hash — NOT copied.
  If a member later changes on disk, the manifest hash makes the
  drift detectable (`pcl validate --strict` may warn; blocking is a
  later decision). A `--copy` durability mode can come later if
  dogfood demands it.
- This resolves F2 WITHOUT a schema change: `test_cases.evidence_id`
  and `defects.evidence_id` stay single-column. Instead of repeatable
  `--evidence` flags and an M:N link table (migration 006), the
  answer is "make one bundle, link its one ID". An M:N table is
  reconsidered only if dogfood shows bundles insufficient.

## Part 3: job completion evidence (F3)

- `pcl jobs complete <job-id> --evidence E-00xx` sets the job's
  existing `latest_evidence_id` pointer (no schema change) so
  `pcl jobs list --json` stops showing empty evidence for jobs whose
  outputs exist.
- Independently: when a job output file exists at `output_path` and
  was ingested, the ingest path already creates evidence — audit why
  `jobs list --json` showed empty evidence in the ax1-moc1 run and
  fix the linkage/read path as part of this work.

## Explicitly out of scope

- Auto-execution or output capture by PLH (`--capture -- <cmd>`):
  recording is manual; PLH does not run the caller's commands.
- M:N evidence link tables (migration) — bundles first.
- Re-recording evidence onto already-terminal test states (F1's
  no-op rule stands; re-verification flow is a later design).
- Content inspection/validation of member files beyond hashing.

## Sequencing (proposed)

1. **0093**: `pcl evidence add` + bundle manifest + adhoc types +
   strict-validate integration (manifest members exist; hash drift
   warning).
2. **0094**: `pcl jobs complete --evidence` + the jobs-list evidence
   visibility audit/fix.

Both are additive CLI + artifact work on schema v5.

## Open decisions for approval

1. Evidence `type` values: `adhoc_artifact` / `adhoc_bundle` as
   proposed, or a single type with a manifest field distinguishing
   arity? (Proposal: two types — cheap to read in lists.)
2. Hash-drift on bundle members in `--strict`: warning (proposed) or
   error?
3. Confirm supersession of `verification feedback --output-file` by
   `pcl evidence add`.
