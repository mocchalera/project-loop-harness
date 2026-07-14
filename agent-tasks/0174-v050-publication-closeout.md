# 0174: v0.5.0 publication closeout

- **Status:** Done; public release independently verified
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** S
- **Dependency:** 0173 local release preparation
- **DB schema:** remains 8
- **Evidence:** `docs/evidence/0174-v050-publication-verification.md`

## Goal

Close the v0.5.0 publication record after the separately authorized release by
independently verifying the immutable public surfaces and synchronizing only
the repository's current factual documentation.

## Scope

1. Confirm that annotated tag `v0.5.0`, remote `main`, and the GitHub Actions
   release run resolve to release commit
   `6bfe9b4a5c5b651c7a4f5c7f4771e65cfa75fdb8`.
2. Confirm that the GitHub Release is public and that Actions run `29334828358`
   completed the build and PyPI publication jobs successfully.
3. Confirm PyPI metadata, artifact hashes, and a clean public-wheel install,
   initialization, validation, and render smoke.
4. Record the results in a reviewable docs evidence file and minimally sync the
   task indexes, roadmap, implementation plan, and v0.5.0 release notes.

## Invariants

- 0173 remains unchanged as the historical local-RC preparation record.
- This closeout performs no push, tag, GitHub Release, PyPI, pipx, launch-post,
  or other external mutation.
- No source, test, dependency, database, schema, `.claude`, `.project-loop`, or
  `pcl.yaml` change is in scope.
- Public verification uses only read-only Git/GitHub/PyPI requests and an
  isolated temporary installation.

## Acceptance

1. The public tag and release workflow resolve to the 0173 release commit.
2. The GitHub Release is published, non-draft, and non-prerelease.
3. Actions run `29334828358` is complete/success and its PyPI job succeeded.
4. PyPI reports version `0.5.0`, non-yanked wheel and sdist files, and the
   independently downloaded wheel matches the published SHA-256.
5. A clean environment imports the PyPI package as `0.5.0` and completes init,
   non-strict doctor, strict validation, and render smoke.
6. `git diff --check` and repository-local Markdown link/integrity checks pass,
   and the final commit contains only the intended documentation files.

## Non-goals

- Repeating or modifying the release operation.
- Preparing or posting launch announcements.
- Repairing historical task records or Project Loop local state.
