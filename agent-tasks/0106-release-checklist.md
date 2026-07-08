# 0106: Release checklist contract

Milestone: v0.2.4 Trust Patch
Priority: P2
Area: docs/release
Origin: docs/project-loop-harness-v0.2.3-third-party-review.md PLH-0108
Implementation: orchestrator-authored — deliverable is `docs/release-checklist.md`

## Goal

Make every release reproducible by contract, capturing the steps and traps
already proven across v0.1.7–v0.2.3 releases.

## Acceptance

- `docs/release-checklist.md` exists and covers: version bump, release note,
  ruff, pytest (matrix), editable-install sanity, build, twine check, sdist
  contract verification, fresh-venv wheel smoke, `pcl validate --strict
  --json`, `pcl render --json`, SECURITY.md supported-versions check, tag →
  GitHub Release → trusted publishing → PyPI verification, local pipx update.
- The v0.2.4 release is executed against this checklist.
