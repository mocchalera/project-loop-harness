# 0248 v0.6.0 public release reconciliation

**Verified:** 2026-08-23

**Outcome:** Published and publicly verified. The GitHub source chain, release
workflow, PyPI files, PyPI Trusted Publishing provenance, and independent public
install all agree on version `0.6.0` and release commit
`da59b068f27becdc6a8bc857709f899787326638`.

**Scope:** GitHub Issue #1. Public verification was read-only. No GitHub issue,
release, tag, workflow, or PyPI state was changed. Historical incomplete proof
records remain unchanged.

## Immutable source chain

| Surface | Factual result |
| --- | --- |
| `origin/main` | `da59b068f27becdc6a8bc857709f899787326638` (`git ls-remote` verified) |
| Tag ref | `refs/tags/v0.6.0` -> annotated tag object `d662754965aab78221d094a87a17dd2d0d4a4ad7` |
| Tag target | `da59b068f27becdc6a8bc857709f899787326638` |
| Tag signature | Unsigned (`verification.reason=unsigned`); the target identity is still exact |
| GitHub Release | `v0.6.0`, release `369029557`, published `2026-08-12T06:22:58Z`, `draft=false`, `prerelease=false`, `target_commitish` set to the exact commit |

Public references:

- Commit: <https://github.com/mocchalera/project-loop-harness/commit/da59b068f27becdc6a8bc857709f899787326638>
- Annotated tag object: <https://api.github.com/repos/mocchalera/project-loop-harness/git/tags/d662754965aab78221d094a87a17dd2d0d4a4ad7>
- Release: <https://github.com/mocchalera/project-loop-harness/releases/tag/v0.6.0>
- Tag ref API: <https://api.github.com/repos/mocchalera/project-loop-harness/git/ref/tags/v0.6.0>

## GitHub Actions

The release-commit CI run was `31568483574`, a successful push run whose
`head_sha` is the exact release commit. All seven jobs were successful:

- `test (3.10)`, `test (3.11)`, `test (3.12)`, `test (3.13)`
- `MCP conformance (ubuntu-latest)`
- `MCP conformance (windows-latest)`
- `Windows CLI smoke`

<https://github.com/mocchalera/project-loop-harness/actions/runs/31568483574>

The release-triggered `Publish Python Package` run was `31569789948`, also with
the exact release `head_sha`, and concluded successfully:

- `Build distributions`: success
- `Publish to PyPI`: success
- `Publish to TestPyPI`: skipped by the workflow's release-event condition

<https://github.com/mocchalera/project-loop-harness/actions/runs/31569789948>

## Distribution bytes and hashes

Every listed public URL was downloaded during this verification. The local
SHA-256 matched the publisher-declared digest and the API-reported size in every
case.

| Distribution | Filename | Size | SHA-256 | Exact URL |
| --- | --- | ---: | --- | --- |
| GitHub Release | `project_loop_harness-0.6.0-py3-none-any.whl` | 879348 | `92146ae77d25db0f0e8199f8efcdb9106c9dabe45f4861c0a95eca316e4efad7` | <https://github.com/mocchalera/project-loop-harness/releases/download/v0.6.0/project_loop_harness-0.6.0-py3-none-any.whl> |
| GitHub Release | `project_loop_harness-0.6.0.tar.gz` | 2119594 | `babe33071eac85fa59bf7ceeedfd2355b3308e885ab3cbd6f929cb40c8a0f7c1` | <https://github.com/mocchalera/project-loop-harness/releases/download/v0.6.0/project_loop_harness-0.6.0.tar.gz> |
| PyPI wheel | `project_loop_harness-0.6.0-py3-none-any.whl` | 879348 | `4857355d108f720feb93497dc17ae53bb9b7502f4549a0f26c1a97cfa655137d` | <https://files.pythonhosted.org/packages/72/57/74c41e09e8c3c6c223cef2452dc848969ba8b7dfcc192ab0766a2e9f8029/project_loop_harness-0.6.0-py3-none-any.whl> |
| PyPI sdist | `project_loop_harness-0.6.0.tar.gz` | 2108651 | `57232c8668540fbe511e7b29f68341381e7851591af82c5ec6f8750d431b7913` | <https://files.pythonhosted.org/packages/d8/61/12e88d1498513912f7cb877ef5641eb13e085089523762208639214c26e9/project_loop_harness-0.6.0.tar.gz> |

The GitHub Release and PyPI hashes intentionally differ because the two
distribution surfaces contain independently built archive bytes. They are not
compared as if they were one file; each file's own URL, size, and digest agrees.
PyPI's release JSON is <https://pypi.org/pypi/project-loop-harness/0.6.0/json>.

## PyPI Trusted Publishing provenance

Both PyPI files expose a provenance object through PyPI's Integrity API. Each
object contains a Sigstore-signed PyPI Publish Attestation v1 whose publisher is:

- kind: `GitHub`
- repository: `mocchalera/project-loop-harness`
- workflow: `publish-pypi.yml`
- environment: `pypi`
- predicate: `https://docs.pypi.org/attestations/publish/v1`

The attestation subject digest is the corresponding PyPI SHA-256 above:

| File | Provenance URL | Subject SHA-256 | Verification |
| --- | --- | --- | --- |
| `project_loop_harness-0.6.0-py3-none-any.whl` | <https://pypi.org/integrity/project-loop-harness/0.6.0/project_loop_harness-0.6.0-py3-none-any.whl/provenance> | `4857355d108f720feb93497dc17ae53bb9b7502f4549a0f26c1a97cfa655137d` | `pypi-attestations 0.0.30 verify pypi`: `OK` |
| `project_loop_harness-0.6.0.tar.gz` | <https://pypi.org/integrity/project-loop-harness/0.6.0/project_loop_harness-0.6.0.tar.gz/provenance> | `57232c8668540fbe511e7b29f68341381e7851591af82c5ec6f8750d431b7913` | `pypi-attestations 0.0.30 verify pypi`: `OK` |

The verification used the exact PyPI file URLs and repository binding:

```bash
pypi-attestations verify pypi \
  --repository https://github.com/mocchalera/project-loop-harness \
  https://files.pythonhosted.org/packages/72/57/74c41e09e8c3c6c223cef2452dc848969ba8b7dfcc192ab0766a2e9f8029/project_loop_harness-0.6.0-py3-none-any.whl
pypi-attestations verify pypi \
  --repository https://github.com/mocchalera/project-loop-harness \
  https://files.pythonhosted.org/packages/d8/61/12e88d1498513912f7cb877ef5641eb13e085089523762208639214c26e9/project_loop_harness-0.6.0.tar.gz
```

Both commands returned `OK`.

## Fresh public install

A new Python 3.13.12 virtual environment installed only from the public PyPI
Simple index with:

```bash
python -m pip install --no-cache-dir --index-url https://pypi.org/simple \
  project-loop-harness==0.6.0
```

Results:

- `pip show project-loop-harness`: version `0.6.0`
- `pcl --version`: `pcl 0.6.0`
- imported `pcl.__version__`: `0.6.0`
- import path: the fresh venv's `site-packages/pcl/__init__.py`
- `pip check`: no broken requirements
- `pcl --help` and `pcl-mcp --help`: passed
- `direct_url.json`: absent; the install was not editable or path-bound

An independent configured consumer, initialized only with that installed public
CLI, passed `pcl init`, `pcl doctor --strict`, `pcl validate --strict`,
`pcl audit check`, and `pcl render`. The audit was clean with 9 DB events, 9
JSONL events, zero anomalies, zero missing evidence files, and no pending or
failed outbox records.

An empty target also initialized successfully, but its generated placeholder
configuration correctly caused strict doctor to report `CHANGE_ME`, empty
command, and missing finish-check warnings. That expected adoption-config gate
is separate from the configured-consumer release smoke above.

## PCL and historical evidence boundary

The fresh reconciliation worktree was created from `origin/main` and had no
inherited `.project-loop/project.db`. After inspecting the non-empty project with
`pcl init --dry-run --json`, the local state was initialized only through the
public CLI. `pcl doctor --strict`, `pcl validate --strict`, and `pcl render` all
passed. `pcl next --target G-0005` returned `target does not exist`; no new Goal
was created and no Goal was closed or repaired in this worktree.

The prior authorized publication run separately reported the one bounded
G-0005 current-proof packet `E-0128` as `COMPLETED_VERIFIED` and public closeout
Evidence `E-0129`. Those local IDs are historical provenance from that run, not
a recreated database claim in this fresh branch. The earlier incomplete records,
including [0247](0247-v060-release-preparation.md), remain historical and are
not promoted to release success.
