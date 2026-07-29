# 0215 v0.5.5 publication closeout

**Verified:** 2026-07-29

**Outcome:** published and publicly verified

## Authorization and boundary

The owner explicitly instructed this task to proceed after the prior turn
stated the next boundary as exact-commit rebuild, push, tag, GitHub Release,
PyPI Trusted Publishing, public install, and pipx verification. No release
announcement, PR, dependency addition, DB migration, workflow-permission
change, or unrelated workspace cleanup was authorized or performed.

## Fail-first correction

The first remote CI run `30425542751` failed before any tag or Release existed.
GitHub Actions resolved Ruff 0.16.0 through the unbounded `ruff>=0.6` dev
dependency, while local verification had used Ruff 0.15.20. Ruff 0.16 expanded
its implicit default rule selection and exposed 323 pre-existing,
out-of-scope findings.

The minimal correction made the established lint contract explicit:

```toml
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F"]
```

A distribution-contract regression protects that baseline. Corrective commit
`9de15bef1c4a4ebb8b43ce6796805d75fa8d610c` changes only
`pyproject.toml` and `tests/test_distribution.py`. PCL Defect `D-0008` was
closed through defect-repair workflow `WR-0010` and deterministic
automated-CI Verification `V-0010`.

## Immutable source chain

- Release commit: `9de15bef1c4a4ebb8b43ce6796805d75fa8d610c`
- Annotated tag: `v0.5.5`
- Annotated tag object: `fc0e33c9c76bc9c2fddd38c781a0eb9edd7a6b57`
- Dereferenced tag target:
  `9de15bef1c4a4ebb8b43ce6796805d75fa8d610c`
- GitHub Release:
  `https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.5`
- Release published: `2026-07-29T05:59:48Z`
- Release is neither draft nor prerelease.

The annotated tag is unsigned. Exact target identity was independently checked
through local Git, `git ls-remote`, and the GitHub Git data API.

## CI and Trusted Publishing

- Corrective release-commit CI run `30425920292`: success.
  - Ruff passed on Python 3.10, 3.11, 3.12, and 3.13.
  - Full pytest, installed CLI smoke, Windows CLI smoke, Ubuntu/Windows MCP
    conformance, distribution build, and extracted-sdist contracts passed.
- Release-triggered workflow `30426728226`: success.
  - Build distributions job `90494699668`: success.
  - Publish to PyPI job `90494804525`: success.
  - TestPyPI job was intentionally skipped by workflow policy.

GitHub Actions emitted platform warnings that several current actions target
deprecated Node.js 20 and were forced onto Node.js 24. The jobs passed; action
version maintenance remains separate from this release.

## Public PyPI artifacts

PyPI reports `project-loop-harness 0.5.5`, `Requires-Python >=3.10`, one wheel,
and one sdist. Both were downloaded from the URLs in the release JSON and
their bytes matched the reported digests.

| Artifact | Size | Uploaded | SHA-256 |
| --- | ---: | --- | --- |
| `project_loop_harness-0.5.5-py3-none-any.whl` | 569776 | `2026-07-29T06:00:50.507101Z` | `873cb065a9a03b123d97a50cceca8fb200e3123e65404912cadef8cbf31ba613` |
| `project_loop_harness-0.5.5.tar.gz` | 1607706 | `2026-07-29T06:00:52.307836Z` | `80aa5682600a5bb6ce9d86149fb21e4460debf24d99087634ebe66d3caef2917` |

PyPI provenance exists for both artifacts. Each attestation names publisher
repository `mocchalera/project-loop-harness`, workflow `publish-pypi.yml`,
environment `pypi`, and the corresponding artifact digest.

The extracted public sdist has byte-identical `pyproject.toml`,
`tests/test_distribution.py`, and `src/pcl/__init__.py` to tag target
`9de15be`. It contains v0.5.5, the explicit Ruff baseline, its regression
assertion, and task 0214 evidence. Local pre-publication archive hashes differ
because the workflow rebuilt archive wrappers from the clean tag; public
artifact identity was established from PyPI rather than inferred from the
local build.

## Public install and independent consumer

The first no-cache install attempt occurred while PyPI's release JSON already
reported 0.5.5 but its Simple index still ended at 0.5.4. That attempt failed
and is retained as propagation evidence. Once the public Simple index listed
0.5.5, the same empty Python 3.13 venv installed
`project-loop-harness==0.5.5` normally from `https://pypi.org/simple/`.

- `pip check`: no broken requirements.
- CLI, imported package, and package metadata: `0.5.5`.
- Import path: the fresh venv's `site-packages`.
- `direct_url.json`: absent; the install is neither editable nor path-bound.
- `pcl-mcp --help`: passed.

A separate config-ready Python consumer was initialized only with that public
CLI:

- init dry-run/apply: passed;
- strict doctor and strict validation: zero findings;
- audit: clean, 9 DB events and 9 JSONL events, zero anomalies;
- render: passed;
- consumer pytest: 1 passed.

## pipx and residual risk

`pipx upgrade project-loop-harness` upgraded the public install from 0.5.4 to
0.5.5. Pipx metadata, `pcl --version`, package metadata, and import all report
0.5.5 from the pipx venv; `pcl-mcp --help` passes and `direct_url.json` is
absent.

Pipx still reports an unrelated pre-existing invalid interpreter for
`haconiwa`; no repair was attempted. The release tag is unsigned, GitHub
Actions has Node 20 deprecation warnings, and external adoption remains
unproven. These are disclosed residuals, not v0.5.5 artifact failures.

## PCL evidence and claim boundary

- Goal `G-0076`, Task `T-0155`, Feature `F-0084`, Story `US-0088`
- Tests `TC-0204` / `TC-0205`: passing
- Exact local artifact Evidence `E-0703`
- Corrective CI Evidence `E-0704`
- Defect closure Evidence `E-0705`
- Public release/install/pipx Evidence `E-0706`

This release proves artifact integrity and engineering verification. It makes
no external adoption, activation, or reuse claim.
