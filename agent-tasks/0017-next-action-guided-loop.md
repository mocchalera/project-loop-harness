# Task 0017: Next-Action Guided Loop

## Goal

Make `pcl next` a clearer loop driver by giving every suggested action a stable machine-readable schema and a human-readable explanation path.

0011-0016 made validation, audit integrity, reporting, escalation, decision, and escalation/decision linkage durable. The next gap is operational: agents and humans should not need to infer whether the returned command is blocking, human-required, or safe to run from free text alone.

## Scope

Add guided next-action metadata to every `pcl next --json` action:

- `priority`;
- `blocking`;
- `requires_human`;
- `safe_to_run`;
- `expected_after`.

Add:

- `pcl next --explain`, a human-readable explanation of the same action;
- dashboard next-action block rendering for the new metadata;
- tests that lock schema stability and priority ordering.

Keep existing `type`, `command`, `reason`, and `target` fields backward-compatible.

## Action Field Semantics

- `priority`: lower number means higher priority.
- `blocking`: whether normal loop progression should stop until this action is handled.
- `requires_human`: whether the action requires human judgment rather than routine agent work.
- `safe_to_run`: whether the suggested command is safe to run mechanically without filling placeholders or making a judgment.
- `expected_after`: the state that should become true after the action is handled.

## Required Priority Order

1. strict validation failure;
10. open escalation;
20. open decision;
30. `needs_human` verification requiring escalation;
40. active workflow lifecycle;
50. open defect lifecycle;
60. open goal continuation;
70. create goal.

## Acceptance criteria

- Every `pcl next --json` result includes the full guided schema.
- `pcl next --strict --json` validation failure keeps precedence and uses the same schema.
- Existing fields remain backward-compatible.
- `pcl next --explain` prints the same action as human-readable text.
- Dashboard next-action block includes priority, blocking, requires-human, safe-to-run, and expected-after metadata.
- Tests cover schema presence, strict precedence, explanation output, dashboard rendering, and representative priority order.
- No schema migration is added.
- No automatic execution is added.

## Do not

- Do not add `pcl next --execute`.
- Do not run external agents from `pcl next`.
- Do not add hosted services or external notifications.
- Do not add schema migrations.
- Do not make dashboard rendering depend on strict validation.
