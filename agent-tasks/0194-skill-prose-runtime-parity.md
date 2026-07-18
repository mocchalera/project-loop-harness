# 0194: Skill Prose / Runtime Parity

- **Status:** Complete
- **Milestone:** Harness Minimization Phase 2
- **Priority:** P0
- **Size:** S
- **Dependency:** 0193 target-bound `pcl next`
- **Project Loop:** Goal `G-0055`, Task `T-0112`, Feature `F-0058`, Story `US-0056`, Test `TC-0124`
- **DB schema:** remains 8

## Problem

The distributed `project-control-loop` Skill still spends several lines asking
the model to detect stale `pcl next` routing manually. Task 0193 moved that
invariant into the runtime with exact `--target` binding and a deterministic
`select_target` safe stop. Keeping both procedures duplicates context and risks
contract drift.

## Scope

1. Replace only the current-intent compensation prose that has a one-to-one
   runtime equivalent with concise `pcl next --target` guidance.
2. Keep the canonical, template, and plugin Skill copies byte-identical.
3. Update command examples or tests that freeze the retired wording.
4. Do not remove human gates, write-once Evidence rules, permissions, test
   requirements, or state-mutation rules.

## Acceptance

1. The three distributed Skill copies are byte-identical.
2. Guidance points explicit current intent to `pcl next --target <T-|G->` and
   explains `select_target` without restating a manual comparison algorithm.
3. The diff removes more instruction text than it adds.
4. Skill command-example, parity, and freshness tests pass.
5. No runtime, schema, dependency, or generated dashboard files change.
