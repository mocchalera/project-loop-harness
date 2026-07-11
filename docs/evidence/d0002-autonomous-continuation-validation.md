# D-0002 autonomous continuation and progress orientation validation

**Date:** 2026-07-11

## Dogfood finding

The active source runtime was current (`PYTHONPATH=src`, resolving to the
repository `src/pcl`), `pcl doctor` was healthy, and `pcl next` returned ready
task T-0039 with `run_policy=agent_safe`. The agent still ended its turn after
the previous slice. The user then had to ask what to do, clarify the approval
UX, and separately ask where the roadmap stood.

## Fix

All four active/bundled `project-control-loop` Skill copies now require agents
to:

- run `pcl next --json` after each completed slice or meaningful state change;
- continue automatically for in-scope `agent_safe` actions;
- distinguish `safe_to_run=false` from an actual `requires_human=true` gate;
- stop only for a real human decision, external blocker, explicit scope
  boundary, or separately approval-required operation;
- keep every progress handoff oriented with **Now**, **Done**, **Next**, and
  **Human needed**.

Humans are not expected to ask for status repeatedly or run routine CLI
commands to advance a known loop.

## Verification

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_skill_command_examples.py tests/test_distribution.py
23 passed in 14.86s

PYTHONPATH=src python -m ruff check tests/test_skill_command_examples.py
All checks passed!

git diff --check
exit 0
```

The parity test checks every tracked Skill distribution copy for the
continuation and four-field orientation contract. No DB migration or
dependency was added.
