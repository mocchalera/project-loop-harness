# 0215: v0.5.5 release publication

- **Status:** Done; published and publicly verified
- **Milestone:** v0.5.5 Finish Reliability and Operability
- **Priority:** P0
- **Size:** S
- **Dependency:** completed 0213/0214 corrected local release candidate;
  explicit owner publication instruction
- **Project Loop:** Goal `G-0076`, Task `T-0155`, Feature `F-0084`, Story
  `US-0088`, Tests `TC-0204` / `TC-0205`
- **DB schema:** remains 8

## Goal

Publish the corrected v0.5.5 release commit and independently verify the
complete public artifact and install chain without converting publication into
an external adoption claim.

## Scope

1. Require remote CI to pass on the exact corrected release commit.
2. Create and push an annotated `v0.5.5` tag at that commit.
3. Publish the GitHub Release and verify release-triggered Trusted Publishing.
4. Verify PyPI metadata, provenance, exact artifact hashes, archive contents,
   and a normal no-cache public install.
5. Run strict dogfood in an independent config-ready consumer and upgrade pipx
   to the public version.
6. Preserve immutable PCL and tracked closeout evidence, including fail-first
   CI and Simple-index propagation behavior.

## Invariants

- No tag or Release is created before exact-commit CI succeeds.
- Existing tags, Releases, and PyPI versions are never replaced or retried
  through force.
- No schema migration, dependency, telemetry, workflow-permission change,
  provider execution, launch post, or unrelated repair is added.
- Publication is engineering evidence, not evidence of external adoption.
- Existing `.claude` session state and unrelated worktree files remain
  excluded from commits.

## Acceptance

1. `main`, annotated tag, GitHub Release, package metadata, and public PyPI
   artifacts all resolve to release commit `9de15be` and version 0.5.5.
2. Release-commit CI and Trusted Publishing succeed.
3. Public wheel and sdist bytes match PyPI-reported SHA-256 digests and have
   PyPI provenance for the repository's production publish workflow.
4. A no-cache Simple-index install passes version/import/metadata/MCP checks
   and strict independent consumer init, doctor, validation, audit, render,
   and pytest.
5. Pipx runs the non-editable public v0.5.5 package.

## Completion evidence

- Release commit: `9de15bef1c4a4ebb8b43ce6796805d75fa8d610c`
- Annotated tag object: `fc0e33c9c76bc9c2fddd38c781a0eb9edd7a6b57`
- GitHub Release: `v0.5.5`, published `2026-07-29T05:59:48Z`
- Corrective release-commit CI run: `30425920292`, success
- Trusted Publishing run: `30426728226`, success
- Public wheel SHA-256:
  `873cb065a9a03b123d97a50cceca8fb200e3123e65404912cadef8cbf31ba613`
- Public sdist SHA-256:
  `80aa5682600a5bb6ce9d86149fb21e4460debf24d99087634ebe66d3caef2917`
- No-cache public install, strict consumer dogfood, and pipx upgrade: passed
- Corrective CI Defect `D-0008`: closed through workflow `WR-0010` and
  automated-CI Verification `V-0010`
- Immutable public closeout Evidence: `E-0706`
- `docs/evidence/0215-v055-publication-closeout.md`

No release announcement was performed.
