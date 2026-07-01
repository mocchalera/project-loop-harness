# Task 0040: Test Case Evidence Validation

## Goal

Add strict validation invariants for terminal test case states.

Task 0038 made `user_stories` and `test_cases` first-class state. Passing, failing, and waived test cases now carry evidence through `pcl test pass`, `pcl test fail`, and `pcl test waive`, but `pcl validate --strict` does not yet prove that evidence or the corresponding transition event still exists.

## Scope

Extend `pcl validate --strict` to check:

- `test_cases.status = 'passing'` has a current `evidence_id` that exists and has type `test_case_pass`;
- `test_cases.status = 'failing'` has a current `evidence_id` that exists and has type `test_case_fail`;
- `test_cases.status = 'waived'` has a current `evidence_id` that exists and has type `test_case_waiver`;
- `test_case_passed`, `test_case_failed`, and `test_case_waived` events exist for the corresponding terminal states;
- those transition events include an `evidence_id`;
- at least one linked transition-event evidence record exists with the expected evidence type.

## Acceptance Criteria

- Normal `pcl validate --json` remains backward-compatible.
- Valid test case pass/fail/waive lifecycle examples pass strict validation.
- Missing current evidence, missing transition event, missing event evidence ID, missing evidence row, and wrong evidence type fail strict validation with deterministic messages.
- Tests use CLI commands for valid setup and direct DB corruption only for narrow invariant tests.
- No schema migration is added.

## Do Not

- Do not add a foreign key migration.
- Do not require evidence for `planned`, `missing`, or `blocked` test cases in this task.
- Do not make dashboard rendering depend on strict validation.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service functions except in corruption-focused tests.
