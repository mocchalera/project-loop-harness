# 0202: v0.5.3 local release preparation

- **Status:** Complete
- **Milestone:** v0.5.3 Evidence Integrity and Harness Feedback
- **Priority:** P0
- **Size:** M
- **Dependency:** 0200 Gap Report, 0201 Gap Report integrity hardening, event-anchored strict Evidence resolvers
- **Project Loop:** Goal `G-0060`, Task `T-0124`, Feature `F-0066`, Story `US-0064`, Test `TC-0137`
- **DB schema:** remains 8

## Goal

Prepare a reviewable local v0.5.3 release candidate containing the completed
Evidence-integrity and Gap Report work. Keep publication as a separate,
explicitly authorized operation.

## Scope

1. Align package, runtime, MCP fixture, task index, and release-note surfaces
   on v0.5.3.
2. Describe only commits actually included since public v0.5.2, preserving the
   distinction between artifact integrity and factual validity.
3. Run source QA, scratch-project validation/render, wheel and sdist contracts,
   metadata checks, and a clean wheel-install smoke.
4. Record artifact hashes and exact verification results as durable Evidence.
5. Commit the complete local release candidate without tagging, pushing,
   publishing, or changing pipx.

## Invariants

- No Git tag, push, GitHub Release, PyPI/TestPyPI upload, pipx mutation, or
  external announcement.
- No schema migration, dependency addition, hosted service, telemetry, or
  unrelated repair.
- Existing `.claude` session state and unrelated untracked files remain
  untouched and outside the release commit.
- Public v0.5.2 adoption documents remain historical v0.5.2 records; they are
  not mechanically renamed to v0.5.3.

## Acceptance

1. `pyproject.toml`, `pcl.__version__`, CLI/MCP runtime output, wheel, and
   sdist metadata agree on `0.5.3`.
2. Ruff and the full pytest suite pass from the canonical source checkout.
3. Fresh scratch init, strict doctor/validate, audit, and render pass using
   the worktree source.
4. Wheel and sdist build, `twine check`, extracted-sdist contract, and
   clean-wheel init/strict-validate/render/Gap Report contract smoke pass.
5. SHA-256 hashes, file sizes, commit boundary, known warnings, and publication
   boundary are reviewable in a new write-once Evidence note.
