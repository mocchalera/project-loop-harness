# P1-B Atomic Task Accept correction evidence

## Authority and boundary

- correction authority: independent fixed-hash review task `7ad4fd0f`, report `seq1`
- correction base: `5623faf2bce36eb6e0f2e065b22b986fa8b35002`
- schema: `8`; migrations: `0`; runtime dependencies added: `0`
- repository-local `US-0005` remains draft and `F-0004`/`T-0004` remain non-terminal

This correction does not replace immutable Evidence `E-0047`/`E-0048` or
documents `0240`/`0241`.

## Fail-first

The new correction suite initially produced six intended failures:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q -p no:cacheprovider \
  --basetemp=/tmp/plh-p1b-correction-red tests/test_task_accept_correction.py
=> 6 failed in 2.50s
```

The failures covered commit-immediate external member tamper, a pre-existing
valid Task supporting Evidence on replay, newly blocked P0-B readiness during
tail recovery, missing 31-record `PCLF1` authority, divergent M5 effect and
boolean contracts, and divergent canonical human output.

## Corrected contract

- The retained manifest/member/current-proof identity is resealed after the
  final Task event/outbox and immediately before SQLite commit.
- The durable request authority uses canonical `PCLF1` framing, ID reservation
  records and manifest, full live generation records and manifest, and a
  continuous reserved-to-sealed ledger. Two-Test fresh success publishes 31
  records; exact replay publishes zero. Stale precommit prefix advance reserves
  a successor generation without business DML and requires one exact retry.
- M5 uses the versioned 26-field envelope, 25 effect counters, semantic
  accounting, eight byte-exact JSON fixtures, fixed modes/statuses, boolean
  `mutation_committed`, and canonical one-line human output.
- Replay validates the accepted Evidence's own direct outgoing links without
  imposing a singleton constraint on generic inbound Task support.
- Dedicated tail recovery reruns current strict findings and P0-B readiness
  immediately before marker publication and blocks with zero marker/business
  effects when readiness is false.

## Reproducible results

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q -p no:cacheprovider \
  --basetemp=/tmp/plh-p1b-correction-green-7 \
  tests/test_task_accept_correction.py tests/test_task_accept.py \
  tests/test_task_accept_contracts.py tests/test_task_accept_recovery.py
=> 71 passed in 12.87s
```

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q -p no:cacheprovider \
  --basetemp=/tmp/plh-p1b-broad \
  tests/test_prefixed_ids.py tests/test_task_accept.py \
  tests/test_task_accept_correction.py tests/test_task_accept_recovery.py \
  tests/test_task_accept_contracts.py tests/test_event_outbox.py \
  tests/test_mutation_tail.py tests/test_direct_setup.py \
  tests/test_task_terminal_guard.py tests/test_tasks.py tests/test_validation.py \
  tests/test_mcp_server.py tests/mcp/test_external_conformance.py -rs
=> 263 passed, 2 skipped in 48.18s
```

The two skips are the pre-existing Linux-only `/proc` Direct Setup E2E and the
optional official MCP Python SDK conformance import. Dependency installation
was not authorized.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q -p no:cacheprovider \
  --basetemp=/tmp/plh-p1b-correction-full
=> 1479 passed, 2 skipped in 571.11s

PYTHONDONTWRITEBYTECODE=1 ruff check --no-cache .
git diff --check
=> passed
```

PCL validation/render, immutable PCL correction Evidence IDs, and final
commit/hash are recorded at correction handoff after those commands complete.
