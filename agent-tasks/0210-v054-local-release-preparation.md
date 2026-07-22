# 0210: v0.5.4 local release preparation

- **Status:** Complete
- **Milestone:** v0.5.4 Maintainability
- **Priority:** P0
- **Size:** M
- **Dependency:** 0209 Refactoring integrated verification
- **Project Loop:** Goal `G-0063`, Task `T-0133`, Feature `F-0068`, Story `US-0066`, Test `TC-0139`
- **DB schema:** remains 8

## Goal

Prepare a reviewable local v0.5.4 release candidate containing the completed
post-v0.5.3 behavior-preserving CLI and command-service refactor. Keep remote
CI and publication as separate, explicitly authorized operations.

## Scope

1. Align package, runtime, MCP fixture, baseline fixture, task index, and
   release-note surfaces on v0.5.4.
2. Describe only the behavior-preserving refactor included since public
   v0.5.3; do not claim new command or runtime behavior.
3. Run source QA, MCP conformance, advisory retrieval evaluation,
   scratch-project validation/render, wheel and sdist contracts, metadata
   checks, and a clean wheel-install smoke.
4. Record artifact hashes, exact verification results, and known repository
   audit findings as durable Evidence.
5. Commit the complete local release candidate without pushing, tagging,
   publishing, announcing, or changing pipx.

## Invariants

- No Git push or tag, GitHub Release, PyPI/TestPyPI upload, pipx mutation, or
  external announcement.
- No intentional command, flag, output, exit-code, transaction, event,
  Evidence, human-gate, schema, dependency, or generated-artifact change.
- Existing `.claude`, `.playwright-cli`, `.work`, and Project Loop lock files
  remain outside the release commit.
- Public v0.5.3 records remain historical v0.5.3 records; they are not renamed.

## Acceptance

1. `pyproject.toml`, `pcl.__version__`, CLI/MCP runtime output, wheel, and
   sdist metadata agree on `0.5.4`.
2. Ruff, the full pytest suite, optional MCP conformance, and the advisory
   retrieval evaluation pass from the canonical source checkout.
3. A fresh scratch project passes init, strict validation, clean audit, and
   render using the source checkout.
4. Wheel and sdist build, `twine check`, extracted-sdist contracts, and a
   clean-wheel runtime/init/strict-validation/audit/render smoke pass.
5. SHA-256 hashes, file sizes, candidate boundary, known warnings, and the
   publication boundary are reviewable in a new write-once Evidence note.
