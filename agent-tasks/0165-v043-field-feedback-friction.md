# 0165: Resolve v0.4.3 field-feedback finish friction

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** L
- **Dependencies:** 0164
- **DB schema:** no change

## User problem

Real use of PCL 0.4.3 showed that implementation work could finish before the
operator learned that finish checks were missing, a safe documentation check
was blocked, or copied Evidence was not accepted as terminal proof. The same
run also exposed weaker follow-up friction in `pcl next`, Evidence replacement,
PCL-local Git state, intentionally unused commands, and Task–Feature linkage.

The safety direction is correct. The problem is that configuration gaps,
executed-check failures, immutable local proof, and local harness state are not
classified distinctly enough.

## Product outcome

An agent can move from `pcl start` to evidence-backed finish without manual
repository archaeology. Configuration gaps are actionable before close-out;
safe checks and copied proof work as declared; terminal direct-route work does
not spawn redundant coverage; and historical/local state remains auditable
without being treated as active product risk.

## Scope

1. Warn from `pcl start` and `pcl doctor` when no enabled finish check exists.
   Include a minimal `pcl.yaml` example. `pcl finish --emit-packet` returns a
   typed configuration error distinct from an executed check failure.
2. Allow only the exact argv `git diff --check` as a guarded project command.
   Other Git argv remain blocked.
3. Treat a copied Evidence member as healthy when its canonical stored copy is
   present and hash-matching. Missing or drifted original sources, including
   outside-root sources, remain informational. A bad stored copy remains
   unhealthy.
4. When an open Goal's linked Tasks are terminal, route `pcl next` to
   `pcl finish --emit-packet --goal ...`; if finish checks are missing, route to
   the configuration guidance first. Do not recommend `feature_coverage` for
   that direct terminal route.
5. Add `pcl evidence supersede OLD --with NEW --summary ...`. Reuse the existing
   `evidence_links` table and append an event; do not migrate the schema.
   Superseded Evidence stays inspectable but no longer emits active health
   warnings and cannot be reused as terminal proof.
6. Exclude `.project-loop/` runtime artifacts from repository changes and dirty
   risk in completion packets. Expose them separately as optional
   `harness_local_state` in `completion-packet/v1` and finish output.
7. Treat `null` and nested `disabled: true` command entries as intentional
   disablement. Empty strings remain an actionable configuration warning.
8. Add `pcl feature add --task T-XXXX`; create the Feature and update the Task's
   existing `related_feature_id` in one mutation transaction and event trail.

## Invariants

- No new dependency or database migration.
- Every mutation appends an event and projects through the normal outbox.
- The guarded executor still uses `shell=False`; no general Git allowlist.
- Copied proof is judged by canonical stored bytes, not by a later source path.
- Supersession never deletes Evidence, manifests, links, or events.
- Only `.project-loop/` is classified as harness-local; user source and other
  untracked files remain repository changes.
- Existing flat string command configuration remains compatible.
- Feature creation and Task linkage are atomic; invalid or already-linked Tasks
  leave no partial Feature.

## Acceptance

1. Start/doctor/finish missing-check paths are actionable and distinguishable
   from a failed executed check.
2. Exact `git diff --check` passes guarded planning/execution; nearby Git
   commands remain blocked.
3. An outside-root file recorded with `--copy` remains healthy terminal proof
   after the original disappears, while a corrupted copy is rejected.
4. Terminal direct work routes to finish or finish-check setup, never a new
   `feature_coverage` run.
5. Supersession is atomic, idempotence/conflict-safe, visible in Evidence show,
   removes old active warnings, and rejects the old Evidence at terminal use.
6. Harness-only state is visible separately and cannot produce repository-risk
   completion; non-harness dirty files still can.
7. Both supported disable syntaxes produce no empty-command warning and do not
   become finish checks.
8. `feature add --task` round-trips in Task reads and events, with rollback on
   invalid/conflicting Task input.
9. Focused tests, `ruff check .`, full `pytest`, strict validation, fresh-project
   smoke, and rendered dashboard all pass.

## Non-goals

- General shell or Git command execution.
- Evidence deletion or garbage collection.
- Automatic repair of historical warnings.
- Automatic Goal closure or bypassing human decisions.
- Hosted services, telemetry, or publication.
