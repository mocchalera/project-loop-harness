# 0213 v0.5.5 local release-candidate verification

**Verified:** 2026-07-29

**Candidate base before the release-preparation commits:**
`4ee1299215a55cd59b0e132c874d6f2d6760bd5a`

**Outcome:** local release candidate ready for review and remote CI; not
published

## Version and scope

- `pyproject.toml`, `pcl.__version__`, source CLI output, MCP transcript
  fixture, baseline version fixture, wheel metadata, sdist metadata, installed
  import, and installed metadata resolve to `0.5.5`.
- The candidate packages the completed post-v0.5.4 finish input/workspace
  isolation, structured and stability Evidence, compatible-check reuse,
  terminal readiness, explicit attach/routing, scoped audit, bounded retry,
  execution binding, progress receipts, streaming progress, compact output,
  and exact Goal-packet close-routing work through Task 0212.
- Completion-packet/v2, automatic Cockpit ingest, history projection, flake
  quarantine, DB migrations, and dependency additions remain outside this
  release.
- DB schema remains 8. Runtime dependencies remain empty, Python metadata
  remains `>=3.10`, and the optional dependency sets are unchanged.

## Source verification

- `PYTHONPATH=src ruff check .`: passed.
- `PYTHONPATH=src pytest`: 1,268 passed, 1 skipped in 676.21 seconds. The skip
  is the expected official MCP SDK optional-dependency gate in the canonical
  source environment.
- An isolated temporary environment with `mcp==1.28.1` passed all 9 official
  MCP SDK conformance tests in 11.48 seconds.
- `PYTHONPATH=src python scripts/run_advisory_retrieval_eval.py`: completed
  with `ok: true`. The command remains advisory and reported its frozen
  renamed-file known miss rather than treating it as a release failure.
- Version/distribution regression tests passed: 10 passed, 1 expected optional
  MCP skip.
- `PYTHONPATH=src python -m pcl --version`: `pcl 0.5.5`.
- `git diff --check`: passed.

The canonical repository's strict doctor and validation both returned
`ok: true`, zero errors, 4 active and 26 historical warnings. Unfiltered
`pcl audit check --summary --json` remains `issues_found` with 81 human-review
Evidence reconciliation findings: 4 current Evidence corruption findings, 75
source-drift findings with healthy durable copies, and 2 superseded historical
drift findings. There are no repairable or unsupported findings, no
pending/failed outbox rows, and no orphaned Evidence or packet artifacts.

The Task-owned audit scope
`--target T-0153 --since EV-A436149C8A77 --summary` was clean: it scanned the
same 81 repository anomalies, excluded all 81 as unrelated, matched zero, and
reported no unanchored anomaly. This preparation neither repairs, weakens, nor
misclassifies the historical repository findings.

## Source scratch-project verification

A new empty scratch project initialized from the source checkout. Its first
strict doctor correctly rejected the generated `CHANGE_ME` project metadata
and empty command fields. After replacing those placeholders with a valid
Python CLI project name, type, and six non-empty command declarations, the
same scratch project passed:

- strict doctor with zero findings;
- strict validation with zero findings;
- audit with 9 matching SQLite/JSONL events and zero anomalies;
- dashboard render.

The expected template rejection was retained as verification output rather
than hidden or weakened.

## Build and artifact verification

Candidate artifacts were built in `/tmp/pcl-v055-candidate-dist.J52sEZ` after
the task status and release note were finalized and before adding this
self-referential hash note.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `project_loop_harness-0.5.5-py3-none-any.whl` | 569717 | `ce767cddd9fbeefddaa4c5693c70e3e251ab23dd213322ab90739c633ffdb8ea` |
| `project_loop_harness-0.5.5.tar.gz` | 1612949 | `526d0801dc9c262b89c069f1ca54dd9216bb88e45690e9893eadece3da7fd1be` |

- `python -m build --sdist --wheel`: passed.
- `python -m twine check`: passed for both artifacts.
- `python scripts/verify_sdist_contracts.py --dist-dir
  /tmp/pcl-v055-candidate-dist.J52sEZ`: passed; the extracted-sdist contract
  test passed.
- The sdist contains Task 0212, completed Task 0213, and the v0.5.5 release
  note.
- Wheel and sdist metadata report `project-loop-harness 0.5.5` and Python
  `>=3.10`. The wheel has only extra-guarded development/MCP requirements and
  no unconditional runtime dependency.

## Clean-wheel smoke

An isolated environment at `/tmp/pcl-v055-candidate-wheel.UxYXSb` installed
the exact candidate wheel with `--no-deps` and `PYTHONPATH` removed.

- CLI, import, and installed metadata all reported `0.5.5`, with the module
  loaded from the temporary environment's `site-packages`.
- `pcl-mcp --help` passed.
- Fresh init and configured strict doctor/validation returned zero findings.
- Audit was clean with 9 matching SQLite/JSONL events and zero anomalies.
- Dashboard render passed.

## Residual risks and publication boundary

- Local verification used macOS arm64 and Python 3.13.12. Python 3.10-3.12,
  Linux, Windows, and remote official MCP coverage remain dependent on the
  separately authorized remote CI run.
- Setuptools emitted the existing license TOML-table and classifier
  deprecation warnings with a 2027-02-18 deadline. Artifact construction and
  Twine checks passed.
- The local artifact hashes intentionally precede this hash-containing
  Evidence note. Publication must rebuild from the reviewed release commit and
  record or compare the resulting public artifact hashes.
- Existing `.claude`, `.playwright-cli`, `.work`, and Project Loop lock/local
  state remains unrelated and outside the release candidate diff.
- No push, tag, GitHub Release, PyPI/TestPyPI upload, pipx mutation, external
  announcement, or production write occurred.
