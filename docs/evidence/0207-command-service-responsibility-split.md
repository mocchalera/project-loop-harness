# 0207 Command service responsibility split evidence

## Result

`pcl.commands` is now a 54-line compatibility facade over domain operations,
next-action routing, and finish planning. Existing public imports remain valid,
while each responsibility has an explicit one-way dependency boundary.

## Revision

- Implementation commit: `d515542`
- `src/pcl/commands.py`: 2,444 -> 54 lines
- `src/pcl/command_domain.py`: 472 lines
- `src/pcl/action_routing.py`: 1,785 lines
- `src/pcl/finish_planning.py`: 214 lines
- Direct facade characterization: `tests/test_commands_facade.py`

## Verification

- Targeted domain/routing/finish/dashboard tests: 156 passed.
- Final focused facade/next/finish tests: 48 passed.
- Full regression: 1,175 passed, 1 skipped in 324.31s.
- `ruff check .`: passed.
- Source-checkout doctor: passed with zero findings.
- Strict validation: passed with no errors and the unchanged pre-existing
  warning set (three active, 26 historical).
- CLI help, render, and `git diff --check`: passed.

## Boundary review

- Public constants, call signatures, query ordering, transactions, event
  payloads, routing priority, serialized actions, and finish plans are unchanged.
- `start.py`, `renderer.py`, `finish_execution.py`, handlers, and direct test
  imports continue to use `pcl.commands` without changes.
- No dependency, schema, migration, provider, telemetry, or external write.
- Unrelated dirty paths were preserved and excluded from the commit.
