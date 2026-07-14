# 0176 — Explicit Test reverification and legacy Feature receipts

Recorded: 2026-07-15T08:44:00+09:00

## Scope

- Goal `G-0036`, Task `T-0059`
- Defect `D-0007`
- Feature `F-0037`, Story `US-0035`, Test `TC-0099`
- Legacy Features `F-0003` and `F-0004`

## Human approvals

- Cockpit Ask `ask_7531ddf61df3`: the human owner approved legacy Stories
  `US-0001` and `US-0002` exactly as presented.
- Cockpit Ask `ask_515dad837da2`: the human owner approved the dedicated
  `pcl test reverify` contract and explicitly rejected changing the ordinary
  `pcl test pass` idempotent no-op behavior.

## Red evidence

Before implementation, `pytest tests/test_completion_policy.py -q` returned
`2 failed, 7 passed`. Both new acceptance tests failed because argparse did
not recognize `pcl test reverify`.

## Implemented contract

- Adds `pcl test reverify TEST --summary ... --evidence-id E-XXXX
  --completion-policy FILE`.
- Requires a currently passing Test, an approved or waived same-Feature Story,
  an exact target-bound complete Evidence Set, and a passing completion policy.
- Preserves passing status and original `test_case_passed` history.
- Updates the current Evidence pointer and acceptance link and appends one
  `test_case_reverified` event containing the evaluation receipt.
- Rejects invalid status, non-Evidence-Set proof, policy failure, target
  mismatch, or report drift before mutation.
- Makes an exact repeated reverification an event-free no-op.
- Teaches `pcl next`, strict lifecycle validation, and dashboard Done evidence
  to use the latest pass or reverify receipt.

## Legacy receipt modernization

- `TC-0001` -> `E-0329`
- `TC-0002` -> `E-0330`
- `TC-0003` -> `E-0331`
- `TC-0004` -> `E-0332`

All four completion-policy evaluations passed with empty findings. The prior
Evidence IDs remain in the immutable audit history.

## Verification

```text
ruff check .
All checks passed!

pytest tests/test_completion_policy.py tests/test_stories.py tests/test_next_actions.py tests/test_dashboard.py tests/test_skill_command_examples.py tests/test_distribution.py -q
85 passed in 17.75s

pytest
1004 passed, 1 skipped in 214.96s

git diff --check
passed
```

No schema migration, dependency addition, external publication, or remote push
was performed.
