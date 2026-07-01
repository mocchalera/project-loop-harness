# Task 0056: Sandbox No-Op Execution Guard

## Goal

Prevent sandbox execution from reporting success when policy blocks every command and nothing actually runs.

## Scope

- In `pcl workflow sandbox --template workflow_id --execute`, treat zero runnable commands as non-success.
- Mark blocked commands as `skipped` in execute mode even when there are no runnable commands.
- Keep dry-run behavior unchanged.
- Do not record sandbox execution evidence or events for a no-op execution.
- Add regression coverage with a workflow that passes static verification but whose only command is sandbox-blocked.

## Acceptance Criteria

- `--execute` returns `ok: false` when `safe_command_count` is zero.
- The sandbox result keeps `safe_to_execute: false`, `executed_count: 0`, and `evidence_id: ""`.
- Blocked commands are reported with `status: skipped` in execute mode.
- No `workflow_sandbox_run` evidence row is created for the no-op execution.
- No `workflow_sandbox_executed` event is appended for the no-op execution.
- Existing mixed safe/blocked execution still succeeds when safe commands pass.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not execute blocked commands.
- Do not record misleading evidence for work that did not run.
- Do not change workflow verifier acceptance rules.
- Do not add external sandboxing services.
