# Task 0043: Feature Report

## Goal

Add a feature-level evidence report.

Features, user stories, and test cases are now durable state. Operators should be able to review one feature and its evidence trail from a single report command instead of combining dashboard tables, CSV exports, and multiple CLI reads.

## Scope

Add CLI/runtime support for:

- `pcl report feature F-0001`.

The report should include:

- the feature row;
- related user stories;
- related test cases;
- related defects;
- workflow runs related through test cases or defects;
- related agent jobs, verifications, escalations, decisions, evidence, and events.

## Acceptance criteria

- `pcl report feature F-0001 --json` returns `kind: feature`.
- Markdown report is written to `.project-loop/reports/feature-F-0001.md`.
- The Markdown includes stable sections for summary, user stories, test cases, defects, workflow runs, jobs, verifications, human queues, evidence, and events.
- Missing feature IDs return typed JSON errors.
- Tests cover feature report output for coverage context and defect context.
- No schema migration is added.

## Do not

- Do not infer unrelated workflow runs from timestamps alone.
- Do not mutate project-loop state while generating a report.
- Do not make dashboard rendering depend on report generation.
