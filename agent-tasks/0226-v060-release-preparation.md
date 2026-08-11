# 0226: v0.6.0 proof-gated release preparation and publication

- **Status:** In progress; local gates only, not published
- **Milestone:** v0.6.0 Terminal Authority and Mainline Progress Guard
- **Priority:** P0
- **Size:** M
- **Dependency:** completed tasks 0216-0225 and explicit owner publication authority
- **Project Loop:** Goal `G-0005`; current proof and closeout remain mandatory
- **DB schema:** remains 8

## Goal

Turn the completed v0.6.0 implementation into one exact, reviewable release
candidate; prove it within the fixed current-proof bound; then publish and
verify the immutable public chain only while every gate remains green.

## Scope

1. Repair only evidence-proven current-proof blockers without weakening
   parent-sealed authority, process lifetime checks, atomic/hash ordering, or
   fail-closed semantics.
2. Align version, README/release note, supported-version, task-index, and
   distribution surfaces for v0.6.0.
3. Run targeted acceptance, Ruff, compileall, the fresh full source suite,
   exact-candidate package/Twine/sdist/fresh-wheel checks, and one G-0005
   current proof with the fixed 1200-second bound.
4. Close PCL state only through `pcl` commands and only from a green
   authoritative completion packet; then audit, strictly validate, and render.
5. Fast-forward `origin/main`, require every main CI job green, create an
   annotated `v0.6.0` tag at the exact release commit, publish the GitHub
   Release, and verify release-triggered Trusted Publishing.
6. Verify public PyPI wheel/sdist metadata, hashes, provenance, and a no-cache
   public-only install with CLI/init/doctor/validate/render smoke.

## Invariants

- No force push, tag move, history rewrite, retry of an unchanged failure,
  timeout extension beyond 1200 seconds, pipx mutation, or announcement.
- E-0086/E-0088 and unregistered E-0091 retain independent incomplete
  provenance and cannot become release success evidence.
- Schema, runtime dependencies, public finish lifecycle, timeout/retry
  semantics, and completion-packet schema do not change.
- User-owned `.claude` and `.project-loop` runtime dirt remains unstaged and
  is never edited or deleted directly.
- Publication stops before the first external write if proof, audit,
  validation, packaging, fast-forward, auth, or exact-commit CI is non-green.

## Acceptance

1. The source and exact built artifacts report 0.6.0 with Python 3.10-3.13,
   schema 8, zero runtime dependencies, and unchanged completion-packet schema.
2. The post-repair full suite and the one G-0005 current proof finish green;
   the packet has parent authority and binds the exact release commit.
3. PCL Goal closure, audit scope, strict validation, and render are green or
   any repository-historical finding is explicitly separated without being
   hidden or promoted.
4. `origin/main` advances only by fast-forward and all required CI jobs pass
   before tag creation.
5. Tag, GitHub Release, Trusted Publishing, PyPI artifacts/provenance, and
   public-only fresh install all resolve to the same version and release commit.

## Stop conditions

Stop before publication for a non-green proof, active audit blocker,
non-fast-forward main, origin drift, product-source conflict, schema migration,
dependency addition, missing authentication, or any need for new human scope.
