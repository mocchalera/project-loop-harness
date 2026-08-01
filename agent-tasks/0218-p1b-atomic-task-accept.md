# 0218: P1-B Atomic Task Accept

- **Status:** Revised-linearization bounded correction implemented and locally verified; independent re-review pending
- **Milestone:** P1-B one-call terminal acceptance
- **Priority:** P1
- **Size:** XL
- **Dependency:** P0-B terminal readiness and P1-A retained-root mutation tail
- **Project Loop:** Goal `G-0004`, Task `T-0004`, Feature `F-0004`, draft Story
  `US-0005`, planned Tests `TC-0025`–`TC-0028`
- **Schema/dependencies:** schema 8; no migration; no runtime dependency
- **Fail-first evidence:** `docs/evidence/0240-p1b-atomic-task-accept-red.md`
- **Correction evidence:** `docs/evidence/0242-p1b-atomic-task-accept-correction.md`
- **Second correction evidence:** `E-0051` / `docs/evidence/0243-p1b-atomic-task-accept-second-correction.md`
- **Final second correction evidence:** `E-0052` /
  `docs/evidence/0244-p1b-atomic-task-accept-second-correction-final.md`
- **Final candidate evidence:** `E-0053` /
  `docs/evidence/0245-p1b-atomic-task-accept-final-candidate.md`
- **Revised-linearization correction:** `E-0054` /
  `docs/evidence/0246-p1b-revised-linearization-correction.md`

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

The earlier closure wording is qualified by the second bounded correction
Evidence `E-0051`: independent re-review found an additional final-reseal race,
seq27 durable-record divergence, and incomplete seq28 nested validation. The
writer has addressed those findings and preserved the generic Task
supporting-Evidence replay and live strict/P0-B tail-recovery behavior, but this
is not independent acceptance. It does not approve `US-0005` or terminalize
repository-local `F-0004`/`T-0004`.

The final second-correction Evidence further qualifies `E-0051`: its first
milestone still reversed the approved postcommit accepted/projection timing.
The final candidate publishes accepted immediately after confirmed SQLite
commit, retains the canonical 25-record projection-failure state, and reserves
the remaining six records for dedicated tail recovery. Independent fixed-hash
re-review remains required.

Final candidate Evidence further qualifies `E-0052` for the distinct
postcommit accepted-publication failure: actual 24-record accounting, a
confirmed-DB seven-record dedicated repair, and subsequent all-zero replay are
now covered without changing the canonical 25+6 projection-recovery contract.

Human authority `ask_cb3c43a0cbd2` supersedes only the impossible requirement
that non-cooperative filesystem bytes remain current through the physical
SQLite commit. The successful final retained-descriptor reseal is now the
filesystem linearization point V, conditional on the staged transaction
committing. Post-V corruption preserves committed business state, returns a
recoverable corruption envelope when observed, and blocks healthy tail
recovery and current-proof consumers until legitimate immutable Evidence
supersedes it. This qualification does not change M1/M2/M3/M4, P0-B, schema 8,
or the Story/human boundary.
`E-0054` immutably supersedes `E-0053`; it is writer Evidence rather than
independent acceptance.

## Verification

Run focused Task Accept, prefixed-ID, MCP, P0-B, P1-A, Evidence, mutation-tail,
validation, next/finish, Skill parity, Ruff, diff, and full pytest suites from
worktree source with bytecode and pytest cache disabled. Record GREEN evidence
separately before independent review.

Second-correction verification completed with the focused Task
Accept/adversarial suite, relevant P0-B/P1-A/outbox/mutation-tail/MCP/Skill
regressions, Ruff and diff checks, and the final full suite (`1492 passed, 2
skipped`). The draft Story remains a deliberate human-semantic blocker for
closing this repository-local PCL Task; independent fixed-hash re-review is
also still pending.
