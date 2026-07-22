# 0206 CLI Stage 3 control and Profile handlers evidence

## Result

Profile/contracts, project control, context/code-index, and planning/report
CLI orchestration now lives in four bounded handler modules. `cli.py` retains
parser construction, global option normalization, handler routing, and shared
top-level error translation.

## Revision

- Implementation commit: `d2e4e32`
- `src/pcl/cli.py`: 3,111 -> 1,893 lines
- New handlers: 1,335 lines across four modules
- Direct characterization: `tests/test_control_handlers.py`

## Verification

- Targeted compatibility tests: 516 passed.
- Direct handler characterization: 4 passed.
- Full regression: 1,173 passed, 1 skipped in 308.98s.
- `ruff check .`: passed.
- Source-checkout doctor: passed with zero findings.
- Strict validation: passed with no errors and the unchanged pre-existing
  warning set (three active, 26 historical).
- CLI help, render, and `git diff --check`: passed.

## Boundary review

- Existing JSON/text/error/exit-code behavior and dry-run/human gates remain
  unchanged.
- Existing `pcl.cli` monkeypatch seams for time and audit failure tests remain
  injectable through the thin router.
- No dependency, schema, migration, provider, telemetry, or external write.
- Unrelated dirty paths were preserved and excluded from the commit.
