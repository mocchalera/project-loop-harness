# 0104: Python 3.10–3.13 CI matrix

Milestone: v0.2.4 Trust Patch
Priority: P2
Area: ci
Origin: docs/project-loop-harness-v0.2.3-third-party-review.md P2-1 (verified: ci.yml pins `python-version: '3.11'` while pyproject classifiers list 3.10/3.11/3.12/3.13)

## Problem

`pyproject.toml` declares `requires-python = ">=3.10"` and classifiers for
3.10–3.13, but CI runs a single Python 3.11. The advertised support range is
not continuously verified.

## Scope

Update `.github/workflows/ci.yml`:

1. Run lint + tests + smoke on a matrix of `["3.10", "3.11", "3.12", "3.13"]`:
   - `ruff check .`
   - `pytest`
   - smoke: `pcl --version`; then in a fresh temp directory `pcl init`
     (note: `pcl init` takes no positional argument, run it inside the temp
     cwd), `pcl validate --strict --json`, `pcl render --json`.
2. Keep build / twine check / sdist contract steps on a single canonical
   version (3.12).
3. Keep total CI time reasonable — matrix jobs run in parallel; do not add
   new workflow files unless the existing one cannot express it.

## Invariants

- Existing CI steps (including the advisory retrieval eval step from 0080)
  keep their current blocking/advisory semantics; the matrix must not turn an
  advisory step into a blocking one or vice versa.
- No changes to pyproject metadata, package code, or tests are expected. If a
  Python-version-specific test failure surfaces, report it in the task output
  rather than papering over it with skips — that finding is the point of this
  task.

## Acceptance

- CI green on all four Python versions (verify with a branch push / PR run or
  `gh run watch` after pushing the branch).
- Classifiers and CI matrix agree.
- Release note mentions the matrix result.
