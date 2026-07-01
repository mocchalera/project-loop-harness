# Task 0042: Report Coverage Context

## Goal

Include feature coverage artifacts in goal and workflow-run reports.

Feature coverage work now records features, user stories, and test cases as durable state. Reports should show that context directly so a reviewer can understand why a coverage goal or run was accepted without cross-checking dashboard data, CSV exports, or separate CLI list commands.

## Scope

Update `pcl report goal` and `pcl report run` to include:

- related features;
- related user stories;
- related test cases;
- related feature/story/test events;
- terminal test case evidence.

Related test cases are discovered from `test_cases.last_run_id` and from `test_case_*` event payloads that reference the workflow run.

## Acceptance criteria

- Goal reports include `features`, `user_stories`, and `test_cases` in JSON output when a goal workflow run has linked test cases.
- Run reports include the same coverage context for that run.
- Markdown reports include `## Features`, `## User Stories`, and `## Test Cases` sections.
- Related `test_case_passed` / `test_case_failed` / `test_case_waived` events appear in the Events section.
- Terminal test case evidence appears in the Evidence section.
- Tests cover goal and run report output.
- No schema migration is added.

## Do not

- Do not infer coverage links from time ranges alone.
- Do not mutate report-related state while generating a report.
- Do not make dashboard rendering depend on report generation.
