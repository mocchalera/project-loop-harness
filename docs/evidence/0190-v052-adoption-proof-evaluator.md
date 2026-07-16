# 0190 v0.5.2 Adoption Proof evaluator evidence

- **Date:** 2026-07-16
- **Goal / Task:** G-0051 / T-0104
- **Feature / Story / Test:** F-0052 / US-0050 / TC-0115
- **Scope:** participant kit, sanitized observation contract, deterministic
  threshold evaluator, and candidate-wheel readiness smoke
- **External actions:** none

## Delivered contract

1. `adoption-observation/v1` accepts an exact, coarse JSON record and rejects
   unexpected fields such as repository URLs.
2. Five records must use unique pseudonymous participant IDs and the same
   candidate ID plus SHA-256.
3. `adoption-proof-evaluation/v1` reports every frozen gate separately.
4. `ready_to_claim` is true only when all cohort, first-time-user, repository
   diversity, healthy-setup median, verified completion, safety, intervention,
   and seven-day reuse gates pass.
5. Exit 0 means all gates pass; exit 1 means valid evidence is incomplete or
   misses a gate; exit 2 means the evidence is invalid.
6. The participant kit separates observation from assistance and treats routine
   maintainer help as an intervention instead of hiding it.

## Targeted verification

```text
PYTHONPATH=src pytest -q tests/test_adoption_proof_evaluator.py tests/test_adoption_docs.py
10 passed in 0.23s

ruff check scripts/evaluate_adoption_proof.py \
  tests/test_adoption_proof_evaluator.py tests/test_adoption_docs.py
All checks passed!
```

Evaluator cases cover passing, incomplete, threshold failure, malformed extra
fields, duplicate participant IDs, inconsistent completion claims, wrong field
types, deterministic stdout, and exit codes.

## Candidate wheel readiness smoke

```text
python -m build --wheel --outdir /tmp/pcl-v052-candidate.gYRSBz
Successfully built project_loop_harness-0.5.1-py3-none-any.whl

sha256:
b840912d85bd8dcde48be0fc94d54a43526411c74eedc521bb7afabef9b10c0b
```

The wheel was installed without dependencies into a fresh venv. A target with
only `pyproject.toml` and `tests/` then produced:

```text
pcl init --dry-run --json
ok: true; Python project and lint/test commands detected; pcl.yaml still absent

pcl init --json
created: true; event_appended: true

pcl doctor --strict --json
ok: true; findings: []; warnings: []

pcl validate --strict --json
ok: true; findings: []; warnings: []
```

The package still reports `0.5.1`; this is an unpublished local candidate, not
a v0.5.2 release. The candidate ID and wheel SHA are therefore mandatory study
bindings. No wheel was sent or published.

## Full QA

The first full run found one docs-contract phrase split by an edit:

```text
1 failed, 1076 passed, 1 skipped in 189.77s
```

After restoring the frozen phrase, targeted tests and Ruff passed, followed by
a clean full rerun:

```text
PYTHONPATH=src pytest -q
1077 passed, 1 skipped in 244.55s

ruff check .
All checks passed!

git diff --check
exit 0
```

## Residual risk

- No external participant outcome exists yet; the evaluator only proves study
  readiness and calculation behavior.
- Candidate build emitted setuptools license-metadata deprecation warnings.
  They do not affect this wheel's install or runtime, but should be repaired in
  a later packaging-maintenance slice before the 2027 enforcement date.
- Observation records remain human-entered. The evaluator validates structure
  and arithmetic; it cannot prove that an observer's input is truthful.
