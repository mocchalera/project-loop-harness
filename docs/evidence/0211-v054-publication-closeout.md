# 0211 v0.5.4 publication closeout

**Verified:** 2026-07-22

**Outcome:** published and publicly verified

## Authorization

- Cockpit Ask `ask_94c2e3188dda` authorized the `main` push and remote CI.
- Cockpit Ask `ask_c7bb0efd6da1` separately authorized the annotated tag,
  GitHub Release, PyPI Trusted Publishing, public verification, pipx upgrade,
  and closeout push.
- No external launch announcement was authorized or performed.

## Immutable source chain

- Release commit: `cbbe31600c7120dd91f9a7b552c44255470a2210`
- Annotated tag object: `0b8170a09357306351e9abcb8d2887c7c3fe90fd`
- Tag target: `cbbe31600c7120dd91f9a7b552c44255470a2210`
- GitHub Release:
  `https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.4`
- Release published at: `2026-07-22T14:52:12Z`
- Release is neither draft nor prerelease.

GitHub's Release API reports `targetCommitish: main`, while the Git tag API
identifies the existing annotated tag object above and binds it directly to the
release commit. The annotated tag is the immutable release identity.

## CI and publication

- Release-commit CI run `29929234892`: success across Python 3.10, 3.11,
  3.12, and 3.13; Ubuntu/Windows MCP conformance; Windows CLI smoke; build;
  installed CLI smoke; advisory retrieval evaluation; and sdist contracts.
- Release-triggered Trusted Publishing run `29930662936`: success.
- Build-distributions job `88959212392`: success.
- Publish-to-PyPI job `88959341623`: success.
- TestPyPI job `88959342753`: intentionally skipped by the production Release
  workflow.

GitHub Actions emitted its platform warning that `actions/checkout@v4`,
`actions/setup-python@v5`, and `actions/upload-artifact@v4` target deprecated
Node.js 20 and were forced onto Node.js 24. The jobs passed; upgrading these
actions remains follow-up maintenance rather than a v0.5.4 publication blocker.

## Public PyPI artifacts

PyPI reports `project-loop-harness 0.5.4`, `Requires-Python >=3.10`, one wheel,
and one sdist. Independently downloaded bytes matched the PyPI JSON digests.

| Artifact | Size | Uploaded | SHA-256 |
| --- | ---: | --- | --- |
| `project_loop_harness-0.5.4-py3-none-any.whl` | 516700 | `2026-07-22T14:53:14.984264Z` | `13ca86848989f04699654734542811dad2c69e8d5c55effafdf85d823454152e` |
| `project_loop_harness-0.5.4.tar.gz` | 1483450 | `2026-07-22T14:53:16.690771Z` | `77e7897cb903e1293958ce313c72556fc4e583bcd15a5dbe07a0d8db17068a0b` |

## Candidate-to-public archive comparison

The local pre-commit candidate recorded wheel SHA-256
`3404a26fff6c4d695bc042700d00ab2a7d7d81a0beb4533be7fd279ed6fec12a`
and sdist SHA-256
`4bca0337743ff66b22cc323f94639a7690558250783c833b38708d51d3efd5cf`.
The release workflow rebuilt from the clean annotated commit, so archive hashes
were expected to be re-established rather than copied from the local build.

- Extracted local and public wheel trees are byte-identical; the wheel hash
  difference is archive-wrapper metadata only.
- The public sdist adds the committed
  `docs/evidence/0210-v054-local-release-preparation.md` and its one
  `SOURCES.txt` entry. All other extracted sdist files are byte-identical.
- The release workflow's Twine and extracted-sdist contract checks passed.

## Clean public install

A new Python 3.13 venv at `/tmp/pcl-v054-public-verify.fYQ3TD` installed
`project-loop-harness==0.5.4` from PyPI with `--no-cache-dir` and no
`PYTHONPATH`:

- CLI, imported package, and installed metadata all reported `0.5.4`;
- an initial empty-directory init succeeded, then strict doctor correctly
  rejected the untouched `CHANGE_ME` project name and empty commands;
- a separate Python project initialized via the config-ready dry-run/apply
  path, detecting project name `project-loop-harness` and lint/test commands;
- strict doctor and strict validation returned zero findings for that
  config-ready project;
- audit was clean with 9 matching SQLite/JSONL events and zero anomalies;
- dashboard render passed.

The empty-directory strict rejection is recorded rather than presented as a
passing check: a generated but unconfigured project is expected to require
human configuration before strict acceptance.

## pipx

`pipx upgrade project-loop-harness` upgraded the installed package from 0.5.3
to 0.5.4. `pipx list --json` reports the non-editable public package with both
`pcl` and `pcl-mcp`, and bare `pcl --version` reports `pcl 0.5.4`.

Pipx still reports an invalid interpreter for unrelated package `haconiwa`.
No repair was attempted because it is outside this release.

## Repository harness state

- `pcl validate --strict --json`: `ok: true`; 3 active and 26 historical
  warnings from pre-existing Evidence/lifecycle history.
- `pcl audit check --json`: 57 pre-existing human-review anomalies: 3 current
  Evidence corruption findings, 52 mutable-source drifts with healthy durable
  copies, and 2 superseded historical drifts. There are no repairable or
  unsupported anomalies, no pending/failed outbox records, and no orphan
  completion packets.
- Validation runs before the final dashboard render.

## Claim boundary

This release proves artifact integrity and engineering verification only. It
does not establish external adoption, activation thresholds, or reuse. No
external launch announcement was performed.
