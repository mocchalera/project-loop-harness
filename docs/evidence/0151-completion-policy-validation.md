# 0151 Completion Policy validation

**Date:** 2026-07-11
**Scope:** `completion-policy/v1`, deterministic read-only evaluation,
Evidence-Set-backed Test terminal preflight, Story-linked Test planning, strict
validation, documentation, and package inclusion.

## Implemented

- Added the packaged `completion-policy/v1` schema and standard-library
  validator with allowlisted JSON predicates.
- Added read-only `pcl completion evaluate`, which verifies the exact Test
  target, Evidence Set completeness, included reports, and current SHA-256
  hashes without consuming IDs or writing state.
- Extended `pcl test pass` with `--completion-policy` for `evidence_set`
  Evidence while retaining the existing adhoc Evidence path.
- Recorded deterministic `completion-evaluation/v1` details in successful
  `test_case_passed` events.
- Rejected prototype verdicts, incomplete Evidence Sets, missing required
  report kinds, and report drift before Test, Feature, link, event, or outbox
  mutation.
- Enforced Story-linked `pcl test plan` in fresh/enforced projects while
  preserving a structured advisory warning for existing advisory projects.
- Extended `evidence-set/v1` targets to include `test_case` without a schema
  migration.

## Verification

### Focused and related regression tests

```text
PYTHONPATH=src python -m pytest -q tests/test_completion_policy.py \
  tests/test_stories.py tests/test_lifecycle_integrity.py \
  tests/test_validation.py
47 passed in 4.85s
```

Coverage includes contract packaging, unsupported-operator rejection,
prototype rejection, incomplete Evidence Sets, missing policy reports, report
hash drift, read-only deterministic evaluation, successful terminal receipt,
strict validation, and enforced/advisory Story planning with zero partial
traces on rejection.

### Full suite and static checks

```text
PYTHONPATH=src python -m pytest
831 passed, 1 skipped in 136.93s

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
exit 0
```

### Package and clean-wheel smoke

```text
python -m build --outdir /tmp/pcl-0151-dist.0u5OfP
```

The build produced:

- `project_loop_harness-0.4.2-py3-none-any.whl`
- `project_loop_harness-0.4.2.tar.gz`

The wheel was installed into
`/tmp/pcl-0151-wheel-smoke.PG4I2O`. From that isolated installation:

- `pcl completion --help` exposed the read-only `evaluate` command;
- `pcl contract validate --type completion-policy/v1
  tests/fixtures/completion_policy/minimal.json --json` returned `ok: true`;
- `pcl.__file__` resolved inside the temporary virtual environment.

## Boundary retained

The policy engine is domain-neutral, JSON-only, deterministic, local, and
standard-library first. It does not execute third-party tools or arbitrary
expressions. A complete external verdict cannot override incomplete required
evidence. DB schema remains 8 and no dependency was added. No commit, tag,
push, release, or publication was performed.
