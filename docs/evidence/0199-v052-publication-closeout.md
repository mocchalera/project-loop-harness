# 0199 v0.5.2 publication closeout

**Verified:** 2026-07-18

**Outcome:** published and publicly verified

## Immutable source chain

- Release commit: `bbe14cf5a8375e72eaa121c1b8a5a96362560d1d`
- Annotated tag object: `7643ce5ff982c79822dcef9dcf77396f55f9cc7a`
- Tag target: `bbe14cf5a8375e72eaa121c1b8a5a96362560d1d`
- GitHub Release:
  `https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.2`
- Release published at: `2026-07-18T09:25:20Z`
- Release is neither draft nor prerelease.

## CI and publication

- The first candidate CI run `29638536535` failed because the newly frozen
  ablation tests could not resolve historical commits from a shallow checkout.
  `docs/evidence/0199-v052-ci-history-repair.md` records the bounded workflow
  repair; no runtime or test expectation was weakened.
- Release-commit CI run `29638815262`: success across Python 3.10, 3.11, 3.12,
  and 3.13; Ubuntu/Windows MCP conformance; Windows CLI smoke; build; Twine;
  installed CLI smoke; and sdist contracts.
- Release-triggered Trusted Publishing run `29639130354`: success.
- Build-distributions job `88066532078`: success.
- Publish-to-PyPI job `88066563827`: success.

## Public PyPI artifacts

PyPI reports `project-loop-harness 0.5.2`, `Requires-Python >=3.10`, one wheel,
and one sdist. Downloaded bytes matched PyPI JSON digests.

| Artifact | Size | Uploaded | SHA-256 |
| --- | ---: | --- | --- |
| `project_loop_harness-0.5.2-py3-none-any.whl` | 487878 | `2026-07-18T09:26:10.519255Z` | `d7f5dda21e721c3405e694991fa7bbc844f7a31daecb4572efd67c48ffc81048` |
| `project_loop_harness-0.5.2.tar.gz` | 1401906 | `2026-07-18T09:26:12.162754Z` | `529e2236628d70cef2efade82a4ff3017649658e960e6c5b3e8afc0e2f1f601b` |

## Clean public install

A new Python 3.13 venv installed
`project-loop-harness==0.5.2` from PyPI with `--no-cache-dir` and no
`PYTHONPATH`:

- `pcl --version`: `pcl 0.5.2`;
- `pcl init` on a fresh temporary project: passed;
- `pcl validate --strict --json`: `ok: true`, no errors or warnings;
- `pcl render --json`: generated dashboard HTML and JSON successfully.

The existing pipx installation was upgraded from 0.5.1 to 0.5.2 and both
`pcl` and `pcl-mcp` are registered. Pipx separately reported an invalid
interpreter for unrelated package `haconiwa`; no repair was attempted because
it is outside this release.

## Claim boundary

The external five-person first-use cohort is still unrun. This release proves
artifact integrity and engineering verification only; it does not prove user
adoption, activation thresholds, or seven-day reuse.
