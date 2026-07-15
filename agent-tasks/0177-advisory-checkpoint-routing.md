# 0177: Advisory checkpoint routing

- **Status:** Complete
- **Milestone:** v0.5.1 Operator Friction
- **Priority:** P0
- **Size:** S
- **DB schema:** no change
- **Human approval:** approved in Cockpit after dogfooding the five-Feature gate

## User problem

The fixed five-Feature checkpoint is labeled non-blocking, but `pcl next`
returns it before normal Task and Goal continuation and marks it as a human
decision. In routine use this creates a ceremonial approval every five small
Features and trains the operator to dismiss governance prompts.

## Product outcome

Keep the five-Feature cadence as a visible integration-review reminder without
stopping normal work by default. Projects that need the old strict behavior can
opt into it explicitly, and projects that do not want cadence reminders can
turn them off.

## Scope

1. Add a schema-free top-level `checkpoint` configuration section:
   - `mode: advisory | blocking | off`, default `advisory`;
   - `feature_interval`, default `5`, minimum `1`.
2. Keep `pcl checkpoint status` event-backed and expose the resolved mode and
   whether the recommendation requires a human.
3. In `advisory` mode, keep the recommendation visible but let `pcl next`
   return the normal Task or Goal action.
4. In `blocking` mode, preserve the existing `checkpoint_review` human gate.
5. In `off` mode, suppress the cadence recommendation.
6. Show an advisory checkpoint as a non-blocking, non-human low-severity
   dashboard attention item.
7. Reject invalid checkpoint configuration through typed CLI errors and
   validation diagnostics.

## Acceptance

1. Five completed Features plus a ready Task returns `work_on_task` under the
   default configuration while checkpoint status remains recommended.
2. The same state returns the human-gated `checkpoint_review` with
   `mode: blocking`.
3. `mode: off` reports no checkpoint recommendation.
4. A configured `feature_interval` replaces the built-in cadence.
5. The dashboard shows advisory checkpoint attention outside the human
   decision queue.
6. Focused tests, lint, full tests, strict validation, render, and completion
   packet closure pass.

## Non-goals

- Changing release, security, data, destructive-operation, repeated-failure,
  Story approval, or Verification human gates.
- Database migrations or dependency additions.
- Automatically recording or dismissing a checkpoint.
