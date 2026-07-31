# 0218: P1-B Atomic Task Accept

- **Status:** Implemented and locally verified; independent review handoff pending
- **Milestone:** P1-B one-call terminal acceptance
- **Priority:** P1
- **Size:** XL
- **Dependency:** P0-B terminal readiness and P1-A retained-root mutation tail
- **Project Loop:** Goal `G-0004`, Task `T-0004`, Feature `F-0004`, draft Story
  `US-0005`, planned Tests `TC-0025`–`TC-0028`
- **Schema/dependencies:** schema 8; no migration; no runtime dependency
- **Fail-first evidence:** `docs/evidence/0240-p1b-atomic-task-accept-red.md`

## Contract

Implement the fixed `pcl task accept T-XXXX --artifact PATH --command CMD
--summary TEXT --copy --test TC-... --json` command and startup-only MCP mode
`task-accept-write`. One copied `adhoc_artifact` Evidence is linked directly to
all selected Tests, their Feature, and the Task. Tests, Feature, Task, events,
and outbox commit in one transaction only after strict current-proof and P0-B
readiness gates. Exact retry has zero effects; different requests conflict.

Durable claims, Evidence reservations, and generation records use exclusive
no-overwrite publication. Source/copy/manifest/ledger drift, supersession,
forks, and ambiguous authority fail closed. Post-commit projection/render
failure returns exit 6 and forbids re-running the original business request.

Story approval remains a separate human-semantic decision. The task's Story is
intentionally draft until a human approves or waives it; implementation and
automated verification do not infer that decision.

## Verification

Run focused Task Accept, prefixed-ID, MCP, P0-B, P1-A, Evidence, mutation-tail,
validation, next/finish, Skill parity, Ruff, diff, and full pytest suites from
worktree source with bytecode and pytest cache disabled. Record GREEN evidence
separately before independent review.

Local final verification completed with the focused Task Accept/adversarial
suite, relevant P0-B/P1-A/outbox/mutation-tail/MCP regressions, Ruff, diff
checks, a fresh-project CLI smoke with zero-effect replay, strict validation,
and the full suite (`1471 passed, 2 skipped`). The draft Story remains a
deliberate human-semantic blocker for closing this repository-local PCL Task.
