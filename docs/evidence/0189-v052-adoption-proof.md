# 0189 v0.5.2 Adoption Proof implementation evidence

- **Date:** 2026-07-16
- **Goal / Task:** G-0051 / T-0104
- **Feature / Story / Test:** F-0051 / US-0049 / TC-0114
- **Scope:** config-ready Python/Node initialization, compressed public entry,
  and frozen external first-use protocol
- **Publication:** none

## Behavior implemented

1. `pcl init --dry-run` and `pcl init` now detect Python projects from
   `pyproject.toml`, `setup.py`, `setup.cfg`, or `requirements.txt` without
   executing project code.
2. Python project names come from PEP 621, Poetry metadata, `setup.cfg`, or the
   directory name. Only declared/configured `ruff`, `mypy`, and `pytest` checks
   are inferred.
3. Detected Python and Node configs write unknown commands as `null`, making
   them explicitly disabled instead of leaving ambiguous empty values.
4. Existing `pcl.yaml` preservation and Node script allowlisting remain intact.
5. README is 195 lines, links the real dashboard and 3-minute demo in the first
   screenful, and reduces the operator model to five moments.
6. `docs/adoption-proof-v0.5.2.md` freezes the five-person, three-repository-type
   protocol and explicitly records that external outcomes are not yet collected.

## Verification

### Behavior and distribution regression

```text
PYTHONPATH=src pytest -q tests/test_cli_init.py tests/test_adoption_docs.py tests/test_distribution.py
35 passed in 8.65s
```

### Full repository QA

```text
ruff check .
All checks passed!

PYTHONPATH=src pytest -q
1071 passed, 1 skipped in 207.37s

git diff --check
exit 0
```

### Fresh Python adoption smoke

The smoke target contained only this repository's `pyproject.toml` and an empty
`tests/` directory before adoption.

```text
PYTHONPATH=src python -m pcl init --target /tmp/pcl-v052-adoption.RpKZgR --dry-run --json
ok: true; dry_run: true; pcl.yaml action: create
detected: Python project project-loop-harness; commands: lint, test
pcl.yaml remained absent after dry-run

PYTHONPATH=src python -m pcl init --target /tmp/pcl-v052-adoption.RpKZgR --json
created: true; event_appended: true

PYTHONPATH=src python -m pcl --root /tmp/pcl-v052-adoption.RpKZgR doctor --strict --json
ok: true; findings: []; warnings: []

PYTHONPATH=src python -m pcl --root /tmp/pcl-v052-adoption.RpKZgR validate --strict --json
ok: true; findings: []; warnings: []

PYTHONPATH=src python -m pcl --root /tmp/pcl-v052-adoption.RpKZgR render --json
ok: true; dashboard and dashboard-data paths returned
```

## Boundaries and residual risk

- Detection is conservative and dependency-free; unusual TOML formatting or
  nonstandard test runners may still require a manual `pcl.yaml` edit.
- Python and Node fixtures are verified locally. Real external-user outcomes
  remain uncollected and must not be inferred from this evidence.
- No version bump, release artifact, tag, push, external post, telemetry,
  provider execution, schema migration, or dependency change occurred.
