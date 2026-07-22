# 0211: v0.5.4 release publication

- **Status:** Done; published and publicly verified
- **Milestone:** v0.5.4 Maintainability
- **Priority:** P0
- **Size:** S
- **Dependency:** completed 0210 local release candidate; explicit owner publication instruction
- **Project Loop:** Goal `G-0064`, Task `T-0134`, Feature `F-0069`, Story `US-0067`, Test `TC-0140`
- **DB schema:** remains 8

## Goal

Publish the reviewed v0.5.4 release commit and verify the complete public
artifact chain without converting artifact publication into an adoption claim.

## Scope

1. Require the reviewed release commit's GitHub CI matrix to pass.
2. Create and push an annotated `v0.5.4` tag at that exact commit.
3. Publish the GitHub Release and verify release-triggered Trusted Publishing.
4. Verify PyPI metadata, exact artifact hashes, archive contents, and a clean
   public install.
5. Upgrade pipx to the released PyPI version and record immutable closeout
   evidence.

## Invariants

- No schema migration, dependency, telemetry, hosted state, provider execution,
  launch post, or unrelated repair is added.
- Publication is engineering evidence, not evidence of external adoption.
- Existing `.claude` session state and unrelated worktree files are excluded
  from release commits.

## Acceptance

1. `main`, annotated tag, GitHub Release, package version, and public PyPI
   artifacts all resolve to v0.5.4.
2. Release-commit CI and Trusted Publishing succeed.
3. Public wheel and sdist bytes match PyPI-reported SHA-256 digests.
4. A clean PyPI install passes version, config-ready init, strict doctor,
   strict validation, audit, and render checks.
5. Pipx runs the non-editable public v0.5.4 package.

## Completion evidence

- Release commit: `cbbe31600c7120dd91f9a7b552c44255470a2210`
- Annotated tag object: `0b8170a09357306351e9abcb8d2887c7c3fe90fd`
- GitHub Release: `v0.5.4`, published `2026-07-22T14:52:12Z`
- Green release-commit CI run: `29929234892`
- Trusted Publishing run: `29930662936`, success
- Public wheel SHA-256:
  `13ca86848989f04699654734542811dad2c69e8d5c55effafdf85d823454152e`
- Public sdist SHA-256:
  `77e7897cb903e1293958ce313c72556fc4e583bcd15a5dbe07a0d8db17068a0b`
- Clean public install, config-ready init, strict doctor/validation, clean
  audit, render, and pipx upgrade: passed
- `docs/evidence/0211-v054-publication-closeout.md`
- Immutable closeout Evidence: `E-0569`
- Final audit/PCL recovery correction:
  `docs/evidence/0211-v054-publication-closeout-correction.md` (`E-0576`)
- PCL completion packet: `E-0575` (`COMPLETED_WITH_RISK`; unrelated dirty
  session state preserved)
