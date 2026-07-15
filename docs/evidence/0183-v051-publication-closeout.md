# Evidence: 0183 v0.5.1 publication closeout

**Date:** 2026-07-15
**Authorization:** Cockpit Ask `ask_6e4c5b339398` = `Continueして公開`
**Scope:** GitHub/PyPI publication and public verification only

## Public source chain

- Release commit: `d3c6606ebdf9f7c61418421b57fe1cf9fdb8ad7e`
- Annotated tag object: `f8c1b1957c607844a5be6c459d84f62b3fe47a0a`
- Peeled tag target: `d3c6606ebdf9f7c61418421b57fe1cf9fdb8ad7e`
- GitHub Release: `https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.1`
- Release published: `2026-07-15T08:52:08Z`
- Latest Release API resolved `v0.5.1`.
- Trusted Publishing workflow:
  `https://github.com/mocchalera/project-loop-harness/actions/runs/29402348375`
- Workflow event/head: `release`, `v0.5.1`, release commit `d3c6606`.
- Workflow result: build passed, sdist contract passed, artifact upload passed,
  PyPI publish passed.

## Public artifacts

The workflow artifact, PyPI JSON metadata, and fresh downloads from
`files.pythonhosted.org` matched byte for byte.

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `project_loop_harness-0.5.1-py3-none-any.whl` | 481828 | `32b2df33131f541a70b32e0e5fcf668b77da5df9a8f9aa27e6fb6a0ba4a0efa4` |
| `project_loop_harness-0.5.1.tar.gz` | 1312277 | `4437260c38419a62abe95309e7ca05cde920dab8f6af504da355a3826c22ede2` |

PyPI metadata reports version `0.5.1` and `Requires-Python >=3.10`.

The public hashes differ from the macOS local candidate hashes because GitHub
Actions rebuilt the distributions on Linux. The immutable public chain is
internally consistent: workflow artifact bytes equal PyPI metadata and
downloaded file bytes.

## Clean public install

A new virtual environment installed exactly
`project-loop-harness==0.5.1` from `https://pypi.org/simple/` with
`--no-cache-dir` and no `PYTHONPATH`. Runtime verification used fixtures
extracted from the public sdist.

- `pcl --version`: `pcl 0.5.1`
- no-index resume compatibility: passed
- valid binding: two bounded refs, both `trust: unverified`, passed
- invalid hash binding: no claim refs and
  `trace_claim_refs:invalid_binding`, passed
- `pcl doctor`: passed for the initialized scratch project
- strict validation: 0 findings
- render: passed

Local verification workspace:
`/tmp/pcl-v051-public-verify.kXxuqU`

## Pre-publication release checks

- Ruff: passed
- Full tests: 1039 passed, 1 skipped
- Repository strict validation: 0 errors, 29 historical warnings
- Twine: wheel and sdist passed
- Extracted-sdist contract test: passed
- Clean local wheel three-path smoke: passed

## Residual limits

- Local and public functional smoke ran on macOS arm64/Python 3.13; GitHub's
  build and contract test ran on Ubuntu/Python 3.11. Python 3.10/3.12 and
  Windows were not separately exercised in this closeout.
- The workflow emitted a Node.js 20 deprecation annotation for current
  `actions/*@v4/v5` actions being forced onto Node.js 24. It did not affect the
  successful build or publish and should be handled as later maintenance.
- Setuptools license metadata deprecations remain due by 2027-02-18.
- Evaluation results are controlled owner dogfood, not external-user adoption.
- No launch announcement, provider run, telemetry, migration, or adoption
  claim was performed.

## Independent verification

Independent Codex task `b7efeaac` rechecked the public tag, commit, latest
GitHub Release, Actions run, PyPI metadata, artifact hashes, and retained
public-install proof in read-only mode. It initially returned two low-severity
documentation-retention findings: stale pre-publication wording in the GitHub
Release body and missing explicit version/doctor output. The Release body was
factually synchronized and
`docs/evaluation/v0.5.1-public-install-smoke.json` was added. Re-review returned
`APPROVED` with no remaining findings.
