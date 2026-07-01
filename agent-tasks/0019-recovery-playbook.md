# Task 0019: Recovery Playbook

## Goal

Document the operator recovery path for strict validation failures, audit-log mismatches, missing evidence, and stale generated artifacts.

The harness can now detect many unsafe states. Operators need a durable, repo-backed playbook that says when to continue, when to rerun deterministic generation, and when to stop for human maintenance.

## Scope

- Add a recovery playbook under `docs/`.
- Link it from `README.md` and `docs/golden-path.md`.
- Cover the first diagnostic commands:
  - `pcl validate --strict --json`;
  - `pcl report validation --strict`;
  - `pcl next --strict --json`;
  - `pcl loop status --json`;
  - `pcl render --json`.
- Explain the difference between:
  - generated artifact staleness;
  - lifecycle state gaps;
  - evidence or verification gaps;
  - audit-log integrity failures;
  - repeated workflow failures that require escalation.
- State that agents must not repair `.project-loop/project.db` or `.project-loop/events.jsonl` directly.
- Include a short evidence packet checklist for human review.
- Add lightweight tests that keep the documented diagnostic commands and guardrails current.

## Acceptance criteria

- Recovery guidance is deterministic and local-only.
- The playbook tells operators to use `pcl` commands for state mutations.
- The playbook distinguishes strict validation failure routing from normal `pcl next` routing.
- README points to the playbook.
- Golden path points to the playbook after validation/render.
- Tests verify the documented validation report and strict next-action flow.
- No schema migration is added.
- No generated dashboard HTML is hand-edited.

## Do not

- Do not add automatic repair commands.
- Do not mutate SQLite or JSONL outside existing `pcl` service functions.
- Do not add external notification integrations.
- Do not introduce hosted recovery services.
- Do not make dashboard rendering depend on strict validation.
