# Task 0038: Story and Test Case Lifecycle

## Goal

Close the feature coverage gap discovered while dogfooding `pcl` on itself: `user_stories` and `test_cases` already exist in the schema, but agents cannot create or advance them through guarded CLI commands.

The harness should keep story and test coverage artifacts inside the same event-backed state machine as goals, defects, decisions, and workflow runs.

## Scope

Add CLI/runtime support for user stories:

- `pcl story draft --feature F-0001 --actor "..." --goal "..." --benefit "..." --expected-behavior "..."`;
- `pcl story review US-0001 --summary "..."`;
- `pcl story approve US-0001 --summary "..."`;
- `pcl story waive US-0001 --reason "..."`;
- `pcl story list [--feature F-0001] [--status draft|review|approved|waived]`;
- `pcl story read US-0001`.

Add CLI/runtime support for test cases:

- `pcl test plan --feature F-0001 [--story US-0001] --type unit|integration|e2e|manual|smoke|acceptance --scenario "..." --expected "..."`;
- `pcl test pass TC-0001 --summary "..." --evidence "..." [--run WR-0001]`;
- `pcl test fail TC-0001 --summary "..." --evidence "..." [--run WR-0001]`;
- `pcl test block TC-0001 --summary "..." [--run WR-0001]`;
- `pcl test missing TC-0001 --summary "..."`;
- `pcl test waive TC-0001 --reason "..."`;
- `pcl test list [--feature F-0001] [--story US-0001] [--status planned|missing|passing|failing|blocked|waived]`;
- `pcl test read TC-0001`.

Integrate with generated dashboard data and HTML:

- expose `user_stories` and `test_cases` top-level dashboard-data rows;
- expose `counts.user_stories` and `counts.test_cases`;
- render Story Coverage and Test Coverage tables from state.

## Acceptance Criteria

- Story and test mutations append durable events.
- JSON output is predictable and typed.
- Invalid identifiers, missing feature/story/run references, invalid statuses, invalid test types, and invalid transitions return typed JSON errors.
- Test pass/fail transitions require explicit evidence and record inline evidence IDs.
- Test transitions can optionally link to an existing workflow run via `last_run_id`.
- A linked story must belong to the same feature as the test case.
- Feature status is updated conservatively:
  - approved stories can advance a discovered feature to `specified`;
  - planned tests can advance a discovered/specified feature to `needs_test`;
  - failing, missing, or blocked tests mark the feature `needs_fix`;
  - passing all non-waived tests for a feature with no open defects can mark it `passing`.
- Dashboard data contract and HTML include story/test rows.
- Tests cover happy paths, invalid links/transitions, evidence requirements, dashboard visibility, and event append behavior.
- No schema migration is added.

## Do Not

- Do not add hosted services or external dependencies.
- Do not let agents write SQLite directly.
- Do not make dashboard rendering depend on strict validation.
- Do not auto-generate stories or tests from model output in this task.
- Do not change the existing database schema.
