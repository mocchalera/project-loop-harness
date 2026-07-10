# v0.4.1 Plan — Integrity Migration

- **Status:** Active
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
2. **0142 lifecycle repair planner:** provide a read-only plan for existing
   inconsistent rows; semantic repairs remain explicit commands.
3. **0143 terminal link repair:** add dedicated, audited Test/Story/Evidence
   link commands without changing same-status no-op behavior.
4. **0144 Skill/runtime provenance:** record Skill paths and content hashes as
   target-bound execution provenance Evidence.
5. **0145 structured diagnostics:** add machine-readable validation findings
   and concrete safe inspection/repair commands while retaining legacy string
   errors and warnings.
6. Dogfood the complete migration path before changing existing projects from
   advisory to enforced lifecycle validation.

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
