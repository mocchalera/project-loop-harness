# 0202 v0.5.3 local release-candidate verification

**Verified:** 2026-07-20

**Candidate base before the release commit:**
`287ea03e1697f0ca408a7cc488ad28e00dd1bd4b`

**Outcome:** local release candidate ready for independent review; not
published

## Version and scope

- `pyproject.toml`, `pcl.__version__`, CLI output, MCP transcript fixture,
  wheel metadata, and sdist metadata resolve to `0.5.3`.
- The candidate packages event-anchored strict Evidence resolution, the
  `gap-report/v1` contract, and Gap Report integrity hardening completed after
  v0.5.2.
- DB schema remains 8. Runtime dependencies remain empty; optional development
  and MCP-test dependencies are unchanged. Python metadata remains `>=3.10`.
- The remote `v0.5.2` tag exists and GitHub reports v0.5.2 as the latest
  published release. No remote state was changed.

## Source verification

- `python -m ruff check .`: passed.
- `PYTHONPATH=src pytest -q`: 1160 passed, 1 skipped in 264.52 seconds.
- The first full run identified only the expected version snapshot delta. The
  current-contract snapshot and its intentional-change log were updated from
  `0.5.2` to `0.5.3`; the focused baseline test then passed 2 tests and the
  final full run passed.
- `PYTHONPATH=src python -m pcl --root . validate --strict --json`: `ok: true`,
  with 3 active and 26 historical pre-existing warnings.
- `PYTHONPATH=src python -m pcl --root . render --json`: passed.
- `git diff --check`: passed.

Repository `pcl audit check --json` remains `issues_found` with 55
human-review Evidence reconciliation findings: 3 current Evidence corruption,
50 source-drift findings with healthy durable copies, and 2 superseded
historical drift findings. These pre-existing repository-history findings were
not repaired or weakened during release preparation; the new scratch projects
both produced clean audits.

## Scratch-project verification

An initial truly empty scratch at
`/tmp/pcl-v053-source-smoke.ZZbGfY` correctly failed strict doctor because the
generic template retains `CHANGE_ME`, empty commands, and no finish check. A
new detected Python project at `/tmp/pcl-v053-source-ready.tNQX21` then passed:

- init dry-run and apply;
- strict doctor and strict validation with zero findings;
- clean audit with 9 matching SQLite/JSONL events and zero anomalies;
- deterministic dashboard render.

This preserves the empty-generic-project safety contract while proving the
config-ready first-use path.

## Build and artifact verification

Final artifacts were built in `/tmp/pcl-v053-final-dist.bBJHhD` after the
release note and task status were finalized.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `project_loop_harness-0.5.3-py3-none-any.whl` | 504394 | `73aa2a34de1c07ddb12e22da477eb41b66e725e036b0252cd5eda94bee2211e7` |
| `project_loop_harness-0.5.3.tar.gz` | 1471601 | `5e18bfeedf7a22153b0c01b6f80fb93cf502bd4318e7557a8a4564a1285d4234` |

- `python -m build`: passed for wheel and sdist.
- `python -m twine check`: passed for both artifacts.
- `python scripts/verify_sdist_contracts.py --dist-dir
  /tmp/pcl-v053-final-dist.bBJHhD`: passed; extracted-sdist contract test passed 1
  test.
- The sdist contains Task 0202 and the v0.5.3 release note.
- Wheel metadata reports project version `0.5.3`, Python `>=3.10`, and no
  unconditional `Requires-Dist` entry.

## Clean-wheel smoke

A new isolated environment at `/tmp/pcl-v053-final-wheel.7Yn5Nc` installed the
final wheel with `--no-deps` and `PYTHONPATH` removed.

- CLI, import, and installed metadata all reported `0.5.3`.
- Packaged `gap-report/v1` validation accepted the minimal fixture.
- Config-ready init dry-run and apply passed.
- Strict doctor and strict validation returned zero findings.
- Audit was clean with 9 matching SQLite/JSONL events and zero anomalies.
- Dashboard render passed.

## Residual risks and publication boundary

- Local verification used macOS arm64 and Python 3.13.12. The Python 3.10-3.12
  and Windows CI matrix was not rerun locally; Windows-specific secure Gap
  Report file creation therefore remains dependent on remote CI/review.
- Setuptools emitted the existing license TOML-table and classifier
  deprecation warnings with a 2027-02-18 deadline. Artifact construction and
  Twine checks passed.
- Artifact hashes identify this local candidate build. A separately authorized
  publication flow must rebuild or byte-compare final artifacts from the
  reviewed release commit.
- No Git tag, push, GitHub Release, PyPI/TestPyPI upload, pipx mutation, or
  external announcement was performed.
