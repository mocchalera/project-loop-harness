# 0146 Work Brief Validation Evidence

- Date: 2026-07-11
- Project Loop target: G-0018 / T-0035
- Feature / Story / Test: F-0016 / US-0014 / TC-0033
- Source baseline: 22997389f3edfe2c36ff18d5c76fba5e7688ff15

## Implemented contract

- Packaged `work-brief/v1` schema and hand-written standard-library validator.
- `route` is not embedded or required; `status` is not mutable artifact state.
- `pcl brief add` and `pcl brief approve` have zero-mutation dry-run paths.
- Approval records actor/reason/target and the exact canonical artifact SHA-256.
- Conflicting target approval fails before event/outbox mutation.
- `pcl brief show` exposes health, approval, and hash drift.
- Task context and resume include only approved references and summary metadata.
- Existing schema-6 context fallback remains supported.

## Commands and results

```text
pytest -q tests/test_work_briefs.py tests/test_contract_cli.py
16 passed in 0.55s

pytest -q tests/test_work_briefs.py tests/test_contract_cli.py tests/test_context.py tests/test_resume.py
94 passed in 11.54s

ruff check .
All checks passed!

pytest -q
exit 0; one existing skip

pytest --collect-only -q
791 tests collected in 0.11s

git diff --check
exit 0
```

The first full-suite run detected an intentional `pcl --help` snapshot delta
for the additive `brief` command. The committed baseline generator updated only
`pcl-help.json`; the next full-suite run passed.

## Residual human gate

US-0014 remains draft. This Evidence can be linked to TC-0033, but the Test and
Feature must not be marked terminal until a human approves or waives the Story.
