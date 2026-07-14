# 0174 v0.5.0 publication verification

**Verified:** 2026-07-14 (Asia/Tokyo)

**Method:** independent, read-only public verification plus an isolated PyPI
install smoke

**Verdict:** PASS — v0.5.0 is publicly released from the approved 0173 release
commit

## Public identity chain

| Surface | Verified fact |
|---|---|
| Release commit | [`6bfe9b4a5c5b651c7a4f5c7f4771e65cfa75fdb8`](https://github.com/mocchalera/project-loop-harness/commit/6bfe9b4a5c5b651c7a4f5c7f4771e65cfa75fdb8), message `release: prepare v0.5.0 local candidate` |
| Remote `main` | `git ls-remote` resolved `refs/heads/main` to the release commit |
| Tag | Annotated tag `v0.5.0` object `dec7cd546e8a167264579cad390a13ecace89f21` resolved to the release commit |
| GitHub Release | [Project Loop Harness v0.5.0](https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0), published `2026-07-14T13:02:06Z`, non-draft, non-prerelease |
| Actions | [Run 29334828358](https://github.com/mocchalera/project-loop-harness/actions/runs/29334828358), release event, head SHA equal to the release commit, `completed/success` |

The Release has no attached GitHub assets. Distribution artifacts are published
through PyPI by the successful workflow; this is an observed packaging choice,
not a missing-publication finding.

## Actions result

The read-only `gh run view` result reported:

| Job | Result | Relevant completed step |
|---|---|---|
| Build distributions | success | build wheel/sdist, check distributions, verify sdist contract, upload workflow artifacts |
| Publish to PyPI | success | publish distributions to PyPI |
| Publish to TestPyPI | skipped | expected for the GitHub Release path |

The workflow ran from `headBranch: v0.5.0` and
`headSha: 6bfe9b4a5c5b651c7a4f5c7f4771e65cfa75fdb8`.

## PyPI artifact verification

[PyPI 0.5.0 JSON](https://pypi.org/pypi/project-loop-harness/0.5.0/json)
reported `project-loop-harness` version `0.5.0`, Python `>=3.10`, and two
non-yanked files:

| File | Size | Uploaded (UTC) | SHA-256 |
|---|---:|---|---|
| `project_loop_harness-0.5.0-py3-none-any.whl` | 473,539 | `2026-07-14T13:03:03.809280Z` | `2884a32110aaf8b54c2bb5617772c7e154aad396eea7e60156457f4d88fd1bf5` |
| `project_loop_harness-0.5.0.tar.gz` | 1,229,154 | `2026-07-14T13:03:05.524947Z` | `84d0ce0527f22a8b700ff353e4dd8e097be3acc7c950a610f71bffb73de9d9f1` |

An independent no-cache `pip download --only-binary=:all:` produced the wheel
SHA-256
`2884a32110aaf8b54c2bb5617772c7e154aad396eea7e60156457f4d88fd1bf5`,
matching PyPI.

## Clean public-install smoke

The smoke used a fresh Python 3.13 virtual environment under `/tmp`, with
`PYTHONPATH` unset:

```text
Successfully installed project-loop-harness-0.5.0
pcl 0.5.0
metadata=0.5.0
module=.../venv/lib/python3.13/site-packages/pcl/__init__.py
```

The installed CLI then produced these results against a fresh temporary
project:

| Check | Result |
|---|---|
| `pcl init --json` | `ok: true`, database and initial event created in the temporary project |
| `pcl doctor --json` | `ok: true`; expected new-project warnings for `CHANGE_ME`, empty commands, and no finish checks |
| `pcl validate --strict --json` | `ok: true`, zero errors and zero warnings |
| `pcl render --json` | `ok: true`, dashboard data and HTML generated in the temporary project |

For transparency, `doctor --strict` promotes the three untuned new-project
configuration warnings to errors. This is expected onboarding behavior; the
non-strict doctor, strict validator, and render path pass.

## Repository boundary and residual observations

- The closeout worktree began at the release commit with a clean status.
- Its linked-worktree root has no `.project-loop/project.db`; read-only
  `doctor`/`validate` therefore reported `installation_database_missing`.
  Initialization was intentionally not performed, so `.project-loop` remained
  untouched. Functional validation used the isolated public-install project.
- The release commit and annotated tag are unsigned according to GitHub's API.
  Identity is established here by the matching remote ref, tag target, Release
  workflow head SHA, and PyPI artifact chain, not by a cryptographic Git
  signature.
- No external write, release, upload, tag, push, pipx change, or public post was
  performed during this closeout.

## Final repository checks

The final docs-only diff passed:

- `git diff --check`: PASS
- local Markdown-link target verification across all eight changed Markdown
  files: PASS
- factual cross-checks for task `0174`, release commit, Release URL, Actions
  run, and PyPI version: PASS
- unchanged checks for 0173, `.claude`, `.project-loop`, and `pcl.yaml`: PASS
- changed-path allowlist review before commit: PASS
