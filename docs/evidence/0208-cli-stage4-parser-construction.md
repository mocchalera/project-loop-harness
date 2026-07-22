# 0208 CLI Stage 4 parser construction evidence

## Result

Parser construction now uses seven command-family builders behind the stable
`pcl.parser.build_parser` facade, which remains re-exported from `pcl.cli`.
Registration order and every existing argparse contract remain unchanged.

## Revision

- Implementation commit: `1a78d7c`
- `src/pcl/cli.py`: 1,893 -> 231 lines
- Parser facade/common code: 36 lines
- Seven family builders: 1,628 lines
- Direct parser characterization: `tests/test_parser_builders.py`

## Verification

- Existing help/baseline/Skill/parser tests: 111 passed.
- Full command-order, top-level help, and representative-default tests: passed.
- Wheel and sdist distribution tests: 4 passed.
- Full regression: 1,178 passed, 1 skipped in 294.91s.
- `ruff check .`: passed.
- Source-checkout doctor: passed with zero findings.
- Strict validation: passed with no errors and the unchanged pre-existing
  warning set (three active, 26 historical).
- CLI help, render, and `git diff --check`: passed.

## Boundary review

- One temporary retrieval-fixture regression was traced to an unnecessary
  direct import in the new parser test; the test was decoupled and the failing
  fixture plus full suite passed afterward.
- Commands, flags, defaults, choices, aliases, help order/text, parser errors,
  source entry point, wheel entry point, and sdist content remain compatible.
- No dependency, schema, migration, provider, telemetry, or external write.
- Unrelated dirty paths were preserved and excluded from the commit.
