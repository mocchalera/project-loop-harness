# 0203: v0.5.3 release publication

- **Status:** Done; published and publicly verified
- **Milestone:** v0.5.3 Evidence Integrity and Harness Feedback
- **Priority:** P0
- **Size:** S
- **Dependency:** completed 0202 local release candidate; explicit owner publication instruction
- **Project Loop:** Goal `G-0061`, Task `T-0125`, Feature `F-0067`, Story `US-0065`, Test `TC-0138`
- **DB schema:** remains 8

## Goal

Publish the reviewed v0.5.3 release commit and verify the complete public
artifact chain without converting artifact publication into an adoption claim.

## Scope

1. Push the reviewed release commit and require its GitHub CI matrix to pass.
2. Create and push an annotated `v0.5.3` tag at that exact commit.
3. Publish the GitHub Release and verify release-triggered Trusted Publishing.
4. Verify PyPI metadata, exact artifact hashes, and a clean public install.
5. Replace the editable pipx source with the released PyPI version and record
   the immutable closeout evidence.

## Invariants

- No schema migration, dependency, telemetry, hosted state, provider execution,
  launch post, or unrelated repair is added.
- Publication is engineering evidence, not evidence of external adoption.
- Existing `.claude` session state and unrelated worktree files are excluded
  from release commits.

## Acceptance

1. `main`, annotated tag, GitHub Release target, package version, and public
   PyPI artifacts all resolve to v0.5.3.
2. Release-commit CI and Trusted Publishing succeed.
3. Public wheel and sdist bytes match PyPI-reported SHA-256 digests.
4. A clean PyPI install passes version, contract, init, strict validation,
   audit, and render checks.
5. Pipx runs the non-editable public v0.5.3 package.

## Completion evidence

- Release commit: `6e49ac43986e8b965f1777eef9a88f7c73236ef6`
- Annotated tag object: `b5eb54666e8b537b17fd459bd1d9aa5cba94db89`
- GitHub Release: `v0.5.3`, published `2026-07-20T06:30:42Z`
- Green release-commit CI run: `29721069992`
- Trusted Publishing run: `29721897474`, success
- Public wheel SHA-256:
  `0ce97a13c6deedf6525a8487aaba8080744e303c96845ee22028ad5bd623c54f`
- Public sdist SHA-256:
  `448166e9ed78c68ccba2c13dd4d9a20038c2e5e105b717ca97d5ebb02b07eb0a`
- Clean public install, Gap Report contract, strict validation, audit, render,
  and pipx replacement: passed
- `docs/evidence/0203-v053-publication-closeout.md`
