# v0.4.1 Plan — Integrity Migration

- **Status:** Complete
- **Date:** 2026-07-11
- **Basis:** `docs/growth-plan-v0.2.4-v0.5.md` v0.4.1,
  `docs/roadmap/integrated/00-executive-roadmap.md` M2.1, and the real-task
  false-completion improvement handoff used for v0.4.0 RC2.

## Objective

Move existing projects from advisory lifecycle findings toward enforced
integrity without silently approving Stories, Evidence, Verifications, or other
semantic decisions on the operator's behalf.

## Implementation order

1. **0141 idle routing:** remove the fabricated idle human gate and route
   explicit intent through `pcl start`.
2. **0142 lifecycle repair planner:** provide a completely plan-only action
   model for existing inconsistent rows; bare/default and `--dry-run` are the
   only modes, and no mutation service is added.
3. **0143 terminal link repair:** consume the 0142 action model to add the
   internal link mutation service, dedicated audited Test/Story/Evidence link
   commands, and explicit `repair lifecycle --apply-structural`, without
   changing same-status no-op behavior.
4. **0144 Skill/runtime provenance:** store canonical provenance JSON as
   schema-8 `execution_provenance` Evidence and anchor its artifact SHA-256 in
   the event before inspecting current Skill hashes.
5. **0145 structured diagnostics:** add machine-readable validation findings
   and concrete safe inspection/repair commands while retaining legacy string
   errors and warnings.
6. **Complete:** dogfood the complete migration path before changing existing
   projects from advisory to enforced lifecycle validation. See
   `docs/dogfood-report-v0.4.1-integrity-migration.md`.
7. **Release gate:** prepare and independently review a local v0.4.1 release
   commit and artifacts. Tagging, pushing, GitHub/PyPI publication, and local
   `pipx` replacement remain separate human-authorized operations.

0142–0145 are dispatched serially. The dependency is one-way: 0142 publishes a
read-only repair-plan action model and 0143 consumes it to implement every link
mutation and structural apply path; 0142 never imports 0143 mutation services.
0145 may reference those concrete commands only after they exist. 0144 precedes
0145 because both touch report surfaces. This serialization also avoids
cross-worker conflicts in the shared CLI, validator, Evidence, report, and
fixture files.

## Boundaries

- Schema 8 remains sufficient for 0141–0145.
- No automatic Story approval/waiver, Goal verification, or human decision.
- Adaptive Entry, work briefs, route policies, explain/override, and generic
  Verification targets remain outside v0.4.1.
- No hosted service, telemetry, core LLM call, or automatic agent launch.

## Exit criteria

- An existing advisory project receives a deterministic repair plan and can be
  repaired through explicit, audited commands.
- A repaired project passes enforced lifecycle validation without fabricated
  approvals.
- Idle projects no longer create human-decision work merely to register an
  already explicit user intent.
- Skill/runtime provenance and structured findings are visible through
  machine-readable report surfaces.
- The package metadata, release notes, source/sdist/wheel contracts, and clean
  wheel installation pass the local release checklist without changing schema,
  dependencies, packet contracts, or lifecycle policy defaults.
