# Task 0047: Feature Coverage Next Action

## Goal

Make `pcl next` point at concrete unfinished feature coverage work before falling back to a generic goal prompt.

Dogfooding showed that once the loop is otherwise green, `pcl next` repeatedly returns `pcl goal create --title 'Reach feature coverage'` even when durable feature rows still have uncovered statuses.

## Scope

Add next-action routing for uncovered features:

- consider features with status `discovered`, `specified`, `needs_test`, or `needs_fix`;
- return the oldest uncovered feature before the generic `create_goal` action;
- keep strict validation, human queues, active workflow runs, retries, defects, proposals, and open goals ahead of this routing.

Action shape:

- type: `cover_feature`;
- command: `pcl goal create --title 'Cover feature F-0001'`;
- target: feature row;
- priority: lower than open goal continuation, higher than generic create goal.

## Acceptance criteria

- `pcl next --json` returns `cover_feature` when no loop is active and an uncovered feature exists.
- Existing `create_goal` behavior remains when no features exist.
- Strict validation failure precedence remains unchanged.
- Existing guided action schema remains stable.
- Tests cover the new routing.
- No schema migration is added.

## Do not

- Do not auto-create goals.
- Do not auto-change feature status.
- Do not bypass human queues, active workflow runs, defects, or proposal review.
- Do not add external dependencies.
