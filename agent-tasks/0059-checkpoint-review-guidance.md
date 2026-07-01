# Task 0059: Checkpoint Review Guidance

## Goal

Use dogfooding feedback to keep Project Loop from optimizing only for small,
safe forward motion.

When several features have been completed, the harness should pause and ask for
a human integration checkpoint before recommending another feature-coverage run.
The checkpoint records commit/package state, UX checklist review, validation
evidence, and the next high-impact product priority as durable evidence.

## Scope

Add local-only CLI/runtime support for:

- `pcl checkpoint status`;
- `pcl checkpoint record --summary "..." --evidence "..." [--review-type integration|commit|ux|release|package]`;
- a `pcl next --json` action named `checkpoint_review` when at least five
  features have been marked `done` since the last recorded checkpoint.

The checkpoint is stored without a schema migration:

- create `checkpoint_review` evidence with `record_inline_evidence`;
- append a `checkpoint_recorded` event;
- derive status from existing feature transition events and the latest
  checkpoint event.

## Acceptance Criteria

- `pcl checkpoint status --json` reports:
  - whether a checkpoint is recommended;
  - the feature threshold;
  - done feature IDs since the latest checkpoint;
  - feature status counts;
  - passed workflow run count since the latest checkpoint;
  - read-only git dirty-worktree metadata when available.
- `pcl checkpoint record --json` creates evidence and appends a
  `checkpoint_recorded` event.
- Invalid checkpoint records return typed JSON errors.
- `pcl next --json` routes to `checkpoint_review` before open-goal continuation
  when the threshold is met.
- Recording a checkpoint clears that recommendation and allows normal goal
  routing to resume.
- Dashboard next-action output shows the checkpoint action through the existing
  next-action block.
- No schema migration is added.

## Do Not

- Do not auto-commit or auto-package.
- Do not add external services.
- Do not mutate `.project-loop/project.db` outside CLI/runtime service
  functions.
- Do not make dashboard rendering depend on strict validation.
