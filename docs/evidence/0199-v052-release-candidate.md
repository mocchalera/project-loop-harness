# 0199 v0.5.2 release-candidate verification

**Verified:** 2026-07-18

**Candidate source before release commit:** `4ccc29f26b4fdcf9d8158f305469ac9c41cba461`

**Outcome:** approved for the separately authorized public release

## Version and scope

- `pyproject.toml`, `pcl.__version__`, CLI, MCP transcript fixture, wheel, and
  sdist resolve to `0.5.2`.
- DB schema remains 8, runtime dependencies remain empty, and supported Python
  versions remain 3.10 through 3.13.
- `TASKS.md` indexes shipped task specs through 0199 and `SECURITY.md` identifies
  `0.5.x` as the supported public line.
- External participant outcomes have not been collected. The candidate makes no
  adoption claim from publication, internal dogfood, or engineering tests.

## Source verification

- `python -m ruff check .`: passed.
- Targeted release tests: 98 passed, 1 skipped.
- Full `python -m pytest -q`: 1122 passed, 1 skipped in 296.74 seconds.
- Repository `pcl validate --strict --json`: `ok: true`, 0 errors, 3 active
  warnings, and 26 historical warnings.
- Repository `pcl render --json`: passed.

The three active warnings predate this release candidate: two refer to missing
temporary/out-of-root Evidence E-0018, and one refers to historical hash drift
on E-0182. They do not identify release-artifact or current-code failure.

## Build and artifact verification

Artifacts were built in the unique temporary directory
`/tmp/pcl-v052-dist.EkGuMi`.

| Artifact | SHA-256 |
| --- | --- |
| `project_loop_harness-0.5.2-py3-none-any.whl` | `0bdcbb61d09a1818563e76121216a2f1a899d6e1f820f839a25b314dcc51f046` |
| `project_loop_harness-0.5.2.tar.gz` | `9540eb0894c0a9beeca66f47d01da1628f54f781a000c963a67a02595f7aaea2` |

- `python -m build`: passed.
- `python -m twine check`: passed for wheel and sdist.
- `scripts/verify_sdist_contracts.py`: required docs, task specs, and adapter
  contract test present; unpacked-sdist test passed.
- The sdist contains Task 0199 and the v0.5.2 release note.
- Clean venv wheel install with `PYTHONPATH` removed reported `pcl 0.5.2`.
- Fresh initialized project strict validation returned `ok: true` with no
  findings; render produced dashboard HTML and JSON successfully.

## Residual boundaries

- Setuptools reports that the TOML-table license declaration and license
  classifier will require modernization before 2027-02-18. This is a build
  deprecation warning, not a v0.5.2 artifact failure.
- The frozen five-person adoption cohort is still open. Task 0189 therefore
  remains active even though its config-ready implementation, protocol, kit,
  and evaluator are packaged.
- Public tag, GitHub Release, Trusted Publishing, PyPI hashes, and clean public
  install must still be verified after the release commit is pushed.
