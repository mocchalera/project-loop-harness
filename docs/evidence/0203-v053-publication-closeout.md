# 0203 v0.5.3 publication closeout

**Verified:** 2026-07-20

**Outcome:** published and publicly verified

## Immutable source chain

- Release commit: `6e49ac43986e8b965f1777eef9a88f7c73236ef6`
- Annotated tag object: `b5eb54666e8b537b17fd459bd1d9aa5cba94db89`
- Tag target: `6e49ac43986e8b965f1777eef9a88f7c73236ef6`
- GitHub Release:
  `https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.3`
- Release published at: `2026-07-20T06:30:42Z`
- Release is neither draft nor prerelease.

## CI and publication

- Release-commit CI run `29721069992`: success across Python 3.10, 3.11,
  3.12, and 3.13; Ubuntu/Windows MCP conformance; Windows CLI smoke; build;
  installed CLI smoke; and sdist contracts.
- Release-triggered Trusted Publishing run `29721897474`: success.
- Build-distributions job `88286464842`: success.
- Publish-to-PyPI job `88286529538`: success.
- TestPyPI was intentionally skipped by the production Release workflow.

GitHub Actions emitted its platform warning that `actions/checkout@v4`,
`actions/setup-python@v5`, and `actions/upload-artifact@v4` target deprecated
Node.js 20 and were forced onto Node.js 24. The jobs passed; upgrading these
actions remains follow-up maintenance rather than a v0.5.3 publication blocker.

## Public PyPI artifacts

PyPI reports `project-loop-harness 0.5.3`, `Requires-Python >=3.10`, one wheel,
and one sdist. Independently downloaded bytes matched the PyPI JSON digests.

| Artifact | Size | Uploaded | SHA-256 |
| --- | ---: | --- | --- |
| `project_loop_harness-0.5.3-py3-none-any.whl` | 504394 | `2026-07-20T06:31:34.657058Z` | `0ce97a13c6deedf6525a8487aaba8080744e303c96845ee22028ad5bd623c54f` |
| `project_loop_harness-0.5.3.tar.gz` | 1462126 | `2026-07-20T06:31:36.400376Z` | `448166e9ed78c68ccba2c13dd4d9a20038c2e5e105b717ca97d5ebb02b07eb0a` |

## Clean public install

A new Python 3.13 venv at `/tmp/pcl-v053-public-verify.DPhCjr` installed
`project-loop-harness==0.5.3` from PyPI with `--no-cache-dir` and no
`PYTHONPATH`:

- CLI, imported package, and installed metadata all reported `0.5.3`;
- the packaged `gap-report/v1` validator accepted the minimal fixture;
- non-empty-project init dry-run and apply passed;
- strict doctor and strict validation returned zero findings;
- audit was clean with 9 matching SQLite/JSONL events and zero anomalies;
- dashboard render passed.

The pipx installation was replaced with the explicit public spec
`project-loop-harness==0.5.3`; both `pcl` and `pcl-mcp` are registered and the
installed package is no longer editable from the local repository. Pipx still
reports an invalid interpreter for unrelated package `haconiwa`; no repair was
attempted because it is outside this release.

## Repository harness state

- `pcl validate --strict --json`: `ok: true`; 3 active and 26 historical
  warnings from pre-existing Evidence/lifecycle history.
- `pcl audit check --json`: 55 pre-existing human-review anomalies, with no
  repairable or unsupported anomalies. This publication does not rewrite
  historical Evidence or repair unrelated records.
- Validation ran before the final dashboard render.

## Claim boundary

This release proves artifact integrity and engineering verification only. It
does not establish external adoption, activation thresholds, or seven-day
reuse. The prepared external first-use cohort remains separate evidence work.
