# Task 0039: Workflow YAML Rule Expressions

## Goal

Make bundled and previously initialized workflow templates robust to simple rule expressions such as `loop.iteration >= 2`.

The current code template quotes that expression, but existing project-local workflow files can still contain the older unquoted form. `pcl loop run defect_repair --defect D-0001` should not fail before state creation solely because a declarative rule expression contains `>`.

## Scope

- Adjust the small workflow YAML parser so plain scalar strings may contain comparison operators such as `>`, `>=`, `<`, `<=`, `==`, and `!=`.
- Continue rejecting unsupported collection, alias, anchor, and block scalar syntax that the parser does not implement.
- Add regression coverage for unquoted rule expressions.
- Add a workflow-run regression test that rewrites a temp initialized `defect_repair.yaml` to the older unquoted form and confirms `pcl loop run defect_repair --defect ...` succeeds.
- Document the rule-expression scalar expectation in the workflow contract.

## Acceptance Criteria

- `parse_workflow_yaml()` accepts `if: loop.iteration >= 2` as a string scalar.
- `pcl loop run defect_repair --defect D-0001` succeeds when an initialized project contains the unquoted legacy rule expression.
- Existing unsupported YAML features remain rejected.
- `ruff check .`, `pytest`, `pcl validate --json`, `pcl validate --strict --json`, and `pcl render --json` pass.
- No schema migration is added.

## Do Not

- Do not replace the parser with a new dependency.
- Do not widen the workflow language into executable code.
- Do not auto-refresh project-local workflow files as a side effect of validation.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions.
