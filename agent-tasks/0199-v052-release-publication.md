# 0199: v0.5.2 release preparation and publication

- **Status:** Active; publication authorized
- **Milestone:** v0.5.2 Reliability and Harness Minimization
- **Priority:** P0
- **Size:** M
- **Dependency:** merged 0184-0198 implementation; explicit owner publication instruction
- **Project Loop:** Goal `G-0056`, Task `T-0120`, Feature `F-0062`, Story `US-0060`, Test `TC-0132`
- **DB schema:** remains 8

## Goal

Prepare, publish, and independently verify v0.5.2 without presenting the
uncollected external first-use cohort as adoption proof.

## Scope

1. Align version, security, task-index, and release-note surfaces on v0.5.2.
2. Run full source QA, strict scratch validation/render, build contracts, and a
   clean wheel-install smoke.
3. Push the reviewed release commit to `main`, tag it, and publish a GitHub
   Release that triggers Trusted Publishing to PyPI.
4. Verify the public tag, release target, Actions run, PyPI metadata and hashes,
   then repeat the clean-install smoke from PyPI.
5. Preserve factual public closeout evidence and update the local pipx install.

## Invariants

- No adoption claim is made from publication, internal dogfood, downloads, or
  the prepared-but-unrun five-person cohort.
- No schema migration, runtime dependency, telemetry, hosted state, provider
  execution, launch post, or unrelated repair is added.
- Existing `.claude` session state and other unrelated dirty files are excluded
  from release commits.

## Acceptance

1. Version surfaces, wheel, sdist, tag, Release, and PyPI agree on v0.5.2.
2. Ruff, full pytest, package contracts, strict validation, and render pass.
3. A fresh public install passes version, init, strict validate, and render.
4. Release notes identify compatibility, semantic changes, evidence, and the
   unresolved external-adoption boundary.
5. Public hashes and workflow results are recorded as reviewable evidence.

## Completion evidence

- Pending publication and public-artifact verification.
