# 0150 Evidence Set validation

**Date:** 2026-07-11
**Scope:** `evidence-set/v1` contract, report-manifest preflight,
plan/record/show CLI, strict validation, documentation, and package inclusion.

## Implemented

- Added the packaged `evidence-set/v1` schema and standard-library validator.
- Added explicit `evidence-report-manifest/v1` input with unique report kinds,
  normalized work-root-relative paths, and `pass` / `fail` / `warning` /
  `unknown` status.
- Added read-only `pcl evidence-set plan`.
- Added `pcl evidence-set record`, which writes one immutable artifact, one
  `evidence_set` row, one target link, and one `evidence_set_recorded` event.
- Added read-only `pcl evidence-set show` and strict artifact/link validation.
- Added excluded-report warnings and deterministic completeness findings for
  required missing, excluded, or non-passing reports.
- Added canonical fixtures, CLI baseline update, README, and
  `docs/evidence-set-v1.md`.

## Verification

### Focused tests

```text
PYTHONPATH=src pytest -q tests/test_evidence_sets.py
11 passed in 0.86s
```

Coverage includes contract packaging, false-complete semantic rejection,
read-only planning, required and optional exclusions, record/show counts,
missing required kinds, malformed JSON, missing manifest/report files, lexical
path escape, symlink escape, duplicate selection, unknown Evidence, zero
mutation traces, stable ordering, and strict rejection of a corrupted artifact.

Related regression set:

```text
PYTHONPATH=src pytest -q tests/test_evidence_sets.py \
  tests/test_baseline_fixtures.py tests/test_evidence_add.py \
  tests/test_validation.py
70 passed in 9.58s
```

### Full suite and lint

```text
ruff check .
All checks passed!

PYTHONPATH=src pytest
824 passed, 1 skipped in 147.97s

git diff --check
exit 0
```

The final focused run added explicit missing-report and lexical-path-escape
branches inside the already-counted invalid-input test and remained green.

### Package and clean-wheel smoke

```text
python -m build --outdir /tmp/pcl-0150-dist.oxZ0iQ
Successfully built project_loop_harness-0.4.2.tar.gz and
project_loop_harness-0.4.2-py3-none-any.whl
```

The wheel inventory contained:

- `pcl/evidence_sets.py`
- `pcl/contracts/evidence_set.py`
- `pcl/contracts/schemas/evidence-set-v1.schema.json`

After installation into `/tmp/pcl-0150-wheel-smoke.Sc2gVq/venv`, both
`pcl evidence-set --help` and
`pcl contract validate --type evidence-set/v1 tests/fixtures/evidence_set/minimal.json --json`
succeeded.

### Fresh-project smoke

The source-tree CLI was exercised at `/tmp/pcl-0150-smoke.vjMYOk` through:

1. `pcl init` and `pcl start`;
2. report-manifest and report creation;
3. report Evidence recording;
4. Evidence Set plan, record, and show;
5. `pcl validate --strict --json`;
6. `pcl render --json`.

The corrected receipt was `E-0004`, `completeness=complete`, with artifact
health `ok`; strict validation returned zero errors/warnings and render passed.
An initial smoke lookup used a hand-assumed Evidence ID and was safely rejected
as `evidence_set_unknown_evidence`; the smoke then used the actual emitted ID.

## Boundary retained

Completeness is relative to the explicit manifest and caller-declared required
kinds. PCL does not claim that the manifest lists every file that could exist,
does not scan outside the work root, and does not interpret domain-specific
report bodies. Task 0151 owns terminal-transition enforcement; 0150 only makes
the completeness receipt durable and inspectable.

DB schema remains 8. No dependency was added. No commit, tag, push, release, or
publication was performed.
