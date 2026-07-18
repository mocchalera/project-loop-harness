# 0195: Shared Task / Goal Target Resolver

- **Status:** Active
- **Milestone:** Harness Minimization Phase 2
- **Priority:** P1
- **Size:** S
- **Dependency:** 0193 target-bound `pcl next`
- **DB schema:** remains 8

## Problem

`pcl next` and `pcl resume` now expose the same bare Task/Goal target grammar,
but each command separately validates prefixes, looks up rows, and constructs
usage errors. Drift between these read-only orientation commands would recreate
the instruction burden removed in 0193.

## Scope

1. Extract a small internal resolver for existing `T-` and `G-` IDs.
2. Preserve each caller's public payload shape, candidate-selection behavior,
   error code, message, details, and exit code.
3. Keep command-specific routing and packet construction in their current
   modules.
4. Add characterization tests for both callers before refactoring.

## Acceptance

1. `next` and `resume` use one Task/Goal ID grammar and lookup boundary.
2. Existing target-bound and resume suites remain byte-for-byte compatible at
   their public JSON/error surfaces.
3. No target-selection policy is moved into the shared resolver.
4. No schema migration, dependency, Skill, dashboard, or MCP change.
5. Targeted tests, Ruff, and full pytest pass.

