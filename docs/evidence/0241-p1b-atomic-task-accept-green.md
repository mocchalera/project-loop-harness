# P1-B Atomic Task Accept GREEN evidence

## Authority and revision

- base: `185a03ed8ddb999ccf354da2d4f86f36119aee7c`
- verified implementation commit: `f339162f86104aeec54628972f0d33ebd09bd6ce`
- branch: `codex/plh-mutation-tail-p0a-20260730`
- schema: `8`
- runtime dependencies added: `0`
- migrations added: `0`
- final design authority: task `7aad46ce`, raw latest report `seq37`
- final independent design review: task `1069b352`, report `seq1`, High 0 / Medium 0 / Low 0
- P0-B final review: task `c12dd3d9`, report `seq2`

## RED to GREEN

The fail-first results are preserved in
`docs/evidence/0240-p1b-atomic-task-accept-red.md`: the prefixed-ID module,
fixed CLI, service, and MCP startup capability did not exist at base HEAD.

The final implementation adds the fixed CLI and startup-only MCP mode, one
copied `adhoc_artifact` directly linked to every selected Test and its Feature,
one atomic lifecycle/event/outbox transaction, receipt-bound current-proof
identity, immutable request/generation ledgers, exact zero-effect replay, and
dedicated post-commit tail recovery.

## Reproducible verification

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -p no:cacheprovider \
  --basetemp=/tmp/pcl-p1b-postcommit-final \
  tests/test_prefixed_ids.py tests/test_task_accept.py \
  tests/test_task_accept_recovery.py tests/test_task_accept_contracts.py \
  tests/test_event_outbox.py tests/test_mutation_tail.py \
  tests/test_direct_setup.py tests/test_task_terminal_guard.py \
  tests/test_tasks.py tests/test_validation.py tests/test_mcp_server.py \
  tests/mcp/test_external_conformance.py -q
```

Result: `255 passed, 2 skipped in 67.14s`.

This suite includes same-request and different-request races, multi-Test
rollback, Story/current-proof/supersession/tamper guards, full-hash request
identity, ledger gaps/forks, strict exactly-once/P0-B strict-free enforcement,
exit and envelope contracts, startup MCP deny/allow/initialize matrices,
projection/render/marker recovery, commit acknowledgement loss, and real
SIGKILL boundaries immediately before and after SQLite commit.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src pytest -p no:cacheprovider \
  --basetemp=/tmp/pcl-p1b-full-final-2 -q
```

Result: `1471 passed, 2 skipped in 531.18s`.

```text
ruff check --no-cache .
git diff --check
```

Result: both passed.

All four Project Loop Skill copies had the same SHA-256:
`d310c6b00c8b3ce76619e385a25f4a4e74f63ad03395df2e6ee5f9ea50f129d7`.

## End-to-end smoke

A new `/tmp` project was initialized and populated through PCL CLI commands
with one in-progress Task, one Feature, one approved Story, and two planned
Tests. The fixed command accepted `pcl.yaml` as copied proof, appended exactly
six ordered events and six outbox rows, and returned `status=accepted` with
Task/Feature done and both Tests passing. The same request with reversed
`--test` order returned `status=already_accepted` and every business, event,
outbox, copy, marker, projection, and render effect equal to zero. Strict
validation then returned active findings 0 and historical findings 0.

## Repository-local PCL state

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pcl --root . validate
--strict --json` returned `ok=true`, active findings 0, and historical findings
0. `pcl render --json` succeeded. The tracked behavior Story `US-0005` remains
draft by design: automated verification does not infer human semantic approval,
so Tests `TC-0025` through `TC-0028`, Feature `F-0004`, and Task `T-0004` are
not falsely marked terminal.

## Self-audit

No unresolved High or Medium issue was found. No known Low implementation risk
is being carried into review. Independent implementation review remains the
next authority step and is not claimed by this evidence.
