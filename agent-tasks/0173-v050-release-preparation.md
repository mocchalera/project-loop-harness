# 0173: v0.5.0 local release preparation

- **Status:** Done; local RC prepared and independently approved
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** M
- **Dependencies:** 0154–0160, 0162–0172
- **DB schema:** remains 8
- **Human approval:** Story US-0033 approved in Cockpit Ask
  `ask_6062b8b11ee7`; the completed local RC was independently approved in
  Cockpit Ask `ask_7db3120d5404` on 2026-07-14

## Goal

Prepare a trustworthy local v0.5.0 release candidate for operator review before
any publication decision.

## Scope

1. Align package, CLI, MCP, SECURITY, task-index, and release-note version
   surfaces on v0.5.0 while preserving historical evidence and fixtures.
2. Run lint, the complete test suite, and a scratch source init/strict
   validation/render smoke after the final tracked edit.
3. Build fresh wheel and sdist artifacts, run Twine and extracted-sdist
   contract checks, and verify a clean-wheel installation without a polluted
   `PYTHONPATH`.
4. Record final artifact SHA-256 values and residual risks in the local
   `.project-loop` release handoff.
5. Create a local release commit containing only the intended tracked release
   surfaces.

## Invariants

- No database migration, dependency addition, hosted service, telemetry,
  provider call, or automatic external action.
- Council remains opt-in and advisory; `continue experiment` remains the human
  adoption outcome.
- Historical release notes and contract-freeze examples retain their original
  version evidence.
- Existing user-owned `pcl.yaml` and `.claude` working-tree changes are not
  modified or committed.
- No tag, push, GitHub Release, PyPI publication, pipx upgrade, or external post.

## Acceptance

1. Source and built-package version surfaces report `pcl 0.5.0`; schema stays 8.
2. `ruff check .`, `git diff --check`, and the full test suite pass.
3. A scratch source project initializes, passes doctor and strict validation,
   and renders successfully.
4. Twine accepts the wheel and sdist; the extracted sdist contains the required
   docs/tasks and passes its packaged contract test.
5. A clean wheel environment loads packaged profile/policy resources and passes
   init, doctor, strict validation, and render smoke without `PYTHONPATH`.
6. The local handoff records artifact hashes, evidence IDs, platform limits,
   and the publication boundary.

## Non-goals

- Publication or public launch material.
- Real-provider Council execution or default Council activation.
- Feature work, refactoring, dependency updates, or historical-state repair.
