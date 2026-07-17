# 0193: Target-Bound `pcl next` Routing

- **Status:** Active
- **Milestone:** Post-v0.5.2 Harness Minimization
- **Priority:** P0
- **Size:** M
- **Dependency:** 0191 field evidence; Cockpit Talk Room `talk_6c805a8c`
- **Project Loop:** Goal `G-0054`, Task `T-0110`, Feature `F-0057`, Story `US-0055`
- **DB schema:** remains 8

## Problem

`pcl next` currently evaluates project-wide state and silently chooses the first
eligible Task or Goal. In repositories with several open work streams, that can
route an agent to older unrelated work even when the user's current intent is
already known. Skill prose asks the agent to detect and compensate for this
runtime ambiguity, which spends context on a check the CLI can enforce
deterministically.

## Design decision

Add an exact, read-only target boundary without encoding a reasoning procedure:

```text
pcl next --target <T-XXXX|G-XXXX> [--strict] [--explain] [--json]
```

- The target syntax matches `pcl resume --target` and is resolved by ID prefix.
- Project-wide human/safety gates retain precedence.
- Ordinary workflow and backlog routing is scoped to the requested Task or Goal.
- Unbound routing returns a guided `select_target` action when actionable work
  spans multiple Goals. Multiple Tasks under one Goal keep deterministic
  priority ordering so the safe-stop does not become a universal pause.
- `pcl start` binds its returned next action to the Task it just created.

## Scope

1. Add `--target` to the `next` CLI and an optional target argument to the
   internal router while preserving unbound callers.
2. Resolve existing Task and Goal IDs, reject malformed or missing IDs with
   usage errors, and return a non-mutating action for terminal targets.
3. Scope normal workflow/task/goal routing to the resolved target.
4. Add a deterministic, schema-compatible `select_target` action for
   cross-Goal ambiguity.
5. Preserve strict-validation precedence and the existing guided-action keys.
6. Bind the post-create action produced by `pcl start`.

## Invariants

- No schema migration, dependency addition, network access, or publication.
- `pcl next` remains read-only and never executes its recommendation.
- No-target behavior remains unchanged for idle and single-Goal projects.
- Open human decisions, escalations, and other project-wide safety gates are
  never hidden by an explicit target.
- Dashboard and MCP callers may continue calling `next_action(paths)` without
  a target and receive a valid guided-action object.
- Candidate ordering and JSON output are deterministic.

## Non-scope

- Product modes such as `lite`, `standard`, or `strict`.
- Skill prose removal before runtime behavior is verified.
- Active-proof versus historical-finding separation.
- Ablation evaluation or direct-flow step reduction.
- Shared target-parser refactoring with `pcl resume`; that can follow after the
  contract is stable.

## Acceptance

1. `pcl next --target T-XXXX --json` returns work for that Task or its Goal,
   except when a project-wide safety gate has precedence.
2. `pcl next --target G-XXXX --json` restricts ordinary routing to that Goal.
3. Malformed or unknown targets exit 2 with a typed JSON error.
4. A terminal target returns exit 0 with a non-mutating terminal action.
5. Multiple actionable Goals without `--target` return deterministic
   `select_target`; one Goal with multiple Tasks keeps existing priority order.
6. Strict validation still precedes target routing.
7. `pcl start` returns a next command bound to its newly created Task.
8. Targeted tests, full pytest, Ruff, fresh-project smoke, strict validation,
   render, and a repository dogfood command pass.

## Later phases

1. Replace only the Skill prose that has a one-to-one runtime or command-guide
   equivalent; consider sharing target parsing with `resume`.
2. Separate active proof from historical findings.
3. Run an eight-task layered ablation across single-session, resume/handoff,
   and human-gate work.
4. Reduce the direct workflow only where the ablation shows a Pareto
   improvement in acceptance, routing, intervention, tokens, calls, and time.

## Stop conditions

- Stop and return to design if the slice requires a migration, dependency, or
  changes beyond the read-only routing boundary.
- Stop if dashboard/MCP/golden-path regressions cannot be explained by the
  additive `select_target` action.
- Split the slice before adding new harness modes or reasoning-policy rules.
