# 0178 — Maintainer entry hardening verification

Recorded: 2026-07-15T10:00:29+09:00

## Scope

- Goal `G-0037`, Task `T-0060`
- Feature `F-0038`, Story `US-0036`
- Tests `TC-0100` and `TC-0101`
- Task specification `agent-tasks/0175-maintainer-entry-hardening.md`

## Red

Before implementation:

```text
pytest tests/test_cli_init.py -q
2 failed, 23 passed
```

Both new cases failed because `pcl.validators` had no runtime-package-root
diagnostic.

## Implemented

- `pcl doctor` now recognizes the Project Loop Harness source checkout from
  `pyproject.toml` and `src/pcl`.
- A mismatched running package root emits the structured warning
  `development_runtime_source_mismatch`, both paths, and an absolute
  source-pinned retry command.
- Matching source runs and ordinary adopted projects remain quiet.
- `pcl validate` is unchanged; this is doctor-only maintainer advice.
- `docs/maintainer-entry-hardening.md` freezes parser, output, error, event,
  mutation, lifecycle, generated-artifact, Skill, and distribution behavior
  before a staged CLI split.

## Verification

```text
ruff check .
All checks passed!

pytest tests/test_cli_init.py tests/test_adoption_docs.py \
  tests/test_skill_command_examples.py tests/test_distribution.py -q
59 passed in 8.70s

pytest
1006 passed, 1 skipped in 194.57s

git diff --check
passed
```

Live matching-source smoke:

```text
PYTHONPATH=src python -m pcl --root . --json doctor
development_runtime_source_mismatch findings: 0

pcl --root . --json doctor
development_runtime_source_mismatch findings: 0
```

The active bare command and source-pinned command both resolved to this
checkout, so the live environment correctly produced no false warning.

No dependency, schema, migration, environment repointing, telemetry, hosted
service, provider execution, or release was introduced.
