# 0198: Evidence-Gated Direct Flow Reduction

- **Status:** Complete (not implemented; 0197 gate returned `modify`)
- **Milestone:** Harness Minimization Phase 5
- **Priority:** P1
- **Size:** M
- **Dependency:** 0197 aggregate recommendation is `proceed`
- **Project Loop:** Goal `G-0055`, Task `T-0118`
- **DB schema:** remains 8 unless separately approved

## Goal

Reduce direct-workflow instruction and tool overhead only where the frozen
0197 ablation demonstrates a Pareto improvement. Preserve the state machine,
human approvals, typed gates, and hash-pinned terminal Evidence.

## Scope gate

1. Read the frozen cohort, raw arm records, aggregate, and evidence report.
2. Name the exact redundant direct-route steps shown by paired traces.
3. Prefer contracting command-guide/Skill prose with a one-to-one runtime
   equivalent. Add a runtime shortcut only when it reduces calls without
   combining or bypassing a human-required transition.
4. Keep Story/Test capture for behavior changes, validation before render,
   event append semantics, and terminal Evidence requirements unchanged.
5. Do not add `lite`, `standard`, `strict`, or another product mode.

## Acceptance

1. The implementation cites the 0197 case/metric that authorizes every removed
   or combined step.
2. The direct route is measurably shorter in instruction bytes or agent-safe
   command calls while producing equivalent durable entities and events.
3. Story approval remains human-required; no agent manufactures an approval
   receipt or terminal proof.
4. Existing public JSON/error contracts remain compatible unless an additive
   field is explicitly characterized and tested.
5. Targeted tests, full pytest, Ruff, strict validation, render, and a fresh
   direct-flow smoke pass.

## Stop conditions

- If 0197 returns `modify` or `stop`, record that result and leave this task
  unimplemented.
- Stop before a migration, dependency, telemetry, hosted backend, or automatic
  external write; each requires separate human approval.
- Reject a reduction that improves cost while regressing acceptance, routing,
  resume, proof, or a human gate.
