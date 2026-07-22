# 0210 v0.5.4 local release-candidate verification

**Verified:** 2026-07-22

**Candidate base before the release-preparation diff:**
`b2ae90279bb10cb348ac0d13b5f0a8299bd7b172`

**Outcome:** local release candidate ready for review and remote CI; not
published

## Version and scope

- `pyproject.toml`, `pcl.__version__`, source CLI output, MCP transcript
  fixture, baseline version fixture, wheel metadata, sdist metadata, installed
  import, and installed metadata resolve to `0.5.4`.
- The candidate packages the completed post-v0.5.3 behavior-preserving split
  of CLI handlers, parser construction, command services, next-action routing,
  and finish planning.
- No command, flag, help, output, exit-code, transaction, event, Evidence,
  human-gate, schema, dependency, or generated-artifact contract changed
  intentionally.
- DB schema remains 8. Runtime dependencies remain empty, Python metadata
  remains `>=3.10`, and the optional dependency sets are unchanged.

## Source verification

- `ruff check .`: passed.
- `pytest -q`: 1,178 passed, 1 skipped in 239.82 seconds. The skip is the
  expected official MCP SDK optional-dependency gate in the canonical source
  environment.
- An isolated environment with `mcp==1.28.1` passed all 9 MCP conformance
  tests.
- `python scripts/run_advisory_retrieval_eval.py`: completed with `ok: true`;
  the command remains advisory and reported its frozen known-miss metrics.
- `PYTHONPATH=src python -m pcl --version`: `pcl 0.5.4`.
- `PYTHONPATH=src python -m pcl doctor --strict --json`: `ok: true`, with 3
  active and 26 historical pre-existing findings.
- `PYTHONPATH=src python -m pcl validate --strict --json`: `ok: true`, with 0
  errors and the same 29 pre-existing warnings.
- `git diff --check`: passed.

Repository `pcl audit check --json` remains `issues_found` with 57
human-review Evidence reconciliation findings: 3 current Evidence corruption,
52 source-drift findings with healthy durable copies, and 2 superseded
historical drift findings. Compared with the integrated refactor Evidence's 55
findings, `E-0551` and `E-0552` now report source drift for their mutable source
notes after commit `b2ae902`; both durable copies remain healthy. There are no
repairable or unsupported findings, no pending/failed outbox rows, and no
orphaned Evidence or packet artifacts. This release preparation does not repair,
weaken, or misclassify those historical repository findings.

## Scratch-project verification

A new empty scratch initialized from the source checkout and passed:

- `pcl init --json`;
- `pcl validate --strict --json` with zero findings;
- `pcl audit check --json` with 9 matching SQLite/JSONL events and zero
  anomalies;
- `pcl render --json`.

## Build and artifact verification

Candidate artifacts were built in `/tmp/pcl-v054-final-dist.jy1dSu` after the
task and release note were finalized and before adding this self-referential
hash note.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `project_loop_harness-0.5.4-py3-none-any.whl` | 516700 | `3404a26fff6c4d695bc042700d00ab2a7d7d81a0beb4533be7fd279ed6fec12a` |
| `project_loop_harness-0.5.4.tar.gz` | 1491670 | `4bca0337743ff66b22cc323f94639a7690558250783c833b38708d51d3efd5cf` |

- `python -m build`: passed for wheel and sdist.
- `python -m twine check`: passed for both artifacts.
- `python scripts/verify_sdist_contracts.py --dist-dir
  /tmp/pcl-v054-final-dist.jy1dSu`: passed; the extracted-sdist contract passed
  its test.
- The sdist contains Task 0210 and the v0.5.4 release note.
- Wheel metadata reports version `0.5.4`, Python `>=3.10`, and only
  extra-guarded development/MCP requirements; it has no unconditional runtime
  dependency.

## Clean-wheel smoke

An isolated environment at `/tmp/pcl-v054-final-wheel.cWNfHm` installed the
candidate wheel with `--no-deps` and `PYTHONPATH` removed.

- CLI, import, and installed metadata all reported `0.5.4`.
- Fresh init and strict validation returned zero findings.
- Audit was clean with 9 matching SQLite/JSONL events and zero anomalies.
- Dashboard render passed.

## Residual risks and publication boundary

- Local verification used macOS arm64 and Python 3.13.12. Python 3.10-3.12,
  Linux, and Windows remain dependent on the separately authorized remote CI
  run.
- Setuptools emitted the existing license TOML-table and classifier
  deprecation warnings with a 2027-02-18 deadline. Artifact construction and
  Twine checks passed.
- The local artifact hashes intentionally precede this hash-containing Evidence
  note. Publication must rebuild from the reviewed release commit and record or
  compare the resulting public artifact hashes.
- Existing `.claude`, `.playwright-cli`, `.work`, and Project Loop lock-file
  state remains unrelated and outside the release candidate diff.
- No push, tag, GitHub Release, PyPI/TestPyPI upload, pipx mutation, external
  announcement, or production write occurred.
