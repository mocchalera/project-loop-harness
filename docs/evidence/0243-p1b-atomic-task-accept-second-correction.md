# P1-B Atomic Task Accept second correction evidence

## Scope and authority

- bounded writer authority: independent fixed-hash re-review task `b59babf1`, report `seq2`
- correction base: `6bfa1c949e9e5e5b2dad0c167d31ac6414cb8bd0`
- schema: `8`; migrations: `0`; runtime dependencies added: `0`
- P1-C, hosted/cloud/telemetry/paid/external behavior: not implemented
- repository semantic boundary remains unchanged: `US-0005=draft`, `T-0004=in_progress`, `F-0004=needs_test`

This Evidence qualifies and supersedes the closure wording in immutable Evidence
`E-0050` / `docs/evidence/0242-p1b-atomic-task-accept-correction.md` and the
corresponding wording in `agent-tasks/0218-p1b-atomic-task-accept.md`. Those
earlier claims did not cover the final-reseal-to-commit tamper window, the exact
seq27 nested record contents, or complete seq28 nested envelope validation.
This document records the bounded writer correction only. Independent
fixed-hash re-review remains the acceptance authority.

## Fail-first record

Before the correction, the new fixed-authority suite produced the intended RED:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-red \
  tests/test_task_accept_second_correction.py
=> 11 failed in 1.34s
```

The failures covered external-process tamper at `MutationConnection.commit`
entry, all seq27 role/key/content divergences, the missing canonical fixture
identity, and nine invalid seq28 nested/cross-field envelopes that previously
serialized.

## Corrected boundaries

- Final current-proof reseal opens no-follow descriptors for the manifest and
  copied member, retains the project-root/ancestor/leaf identities through the
  SQLite commit call, and executes the retained seal at the actual commit
  entrance. External replacement at that boundary raises a precommit integrity
  error; terminal Task/Feature/Test DML and accepted/sealed durable authority do
  not commit.
- The M2 authority remains 31 canonical `PCLF1` records for a two-Test fresh
  success and zero records for exact replay. The exact seq27 roles now carry the
  reservation manifest reference, copy manifest, full target row/link/event
  snapshots, canonical request/plan byte commitments, SQLite/projection/render/
  teardown receipts, generation manifest, temporary-directory name, and one
  reserved-to-sealed head. Recovery regenerates the same canonical tail and
  rejects gaps, forks, corrupt records, or mismatched precommit records.
- The M5 runtime uses the complete Draft 2020-12 nested schema and semantic
  phase/mode/cross-field checks before serialization. The eight approved JSON
  goldens remain byte exact. `safe_to_retry_original=true` is exclusive to
  stale-generation advance; commit-unknown uses
  `process_restart_and_inspect` and never claims a committed mutation.
- M3 remains closed: pre-existing Task supporting Evidence is included in the
  full supporting-link snapshot, while the accepted Evidence's own outgoing
  links remain exact. Fresh succeeds and exact replay reports all 25 effects as
  zero.
- M4 remains closed: dedicated tail recovery reruns live strict validation and
  P0-B readiness before marker publication. A newly active High Defect returns
  exit 6 with zero recovery marker publication and zero business re-execution.

## Fixed authority and source hashes

```text
seq27 raw canonical fixture bytes (without terminal LF): 27074
seq27 raw canonical fixture SHA-256:
07e41045a685aac088ae6323352f8c5d5ecd2173a56fd1e2c23e49c878c64b0b
checked-in fixture bytes (with one repository LF): 27075
checked-in fixture SHA-256:
c1530c086ddde65e6a13cff7cb6d846cf6fbb82213770b5307bcfbbc510b9c92

src/pcl/task_accept.py
62c1ccf9c8232096af3aa11410139f79dcd531964ec1ecd31c7156595f908a8e
src/pcl/db.py
3228985e54166d3800fb0c3211ecbefad593b9a5385bf075a0501722c42d8535
tests/test_task_accept_second_correction.py
7a817b0c3d59c1df164fcfd21ece7dece354bacb4461de2e6bbcb3a15f9775b8
tests/test_task_accept.py
e2ddee29f37f4c1316a75af4f9a295f8bcfdfad98d4a648d688c783b1049e115
tests/test_task_accept_recovery.py
d8876f8c845c82de2c000292761a01029571a08c7822660179306f32293b4552
```

## Reproducible GREEN results

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-focus8 \
  tests/test_task_accept_second_correction.py \
  tests/test_task_accept_recovery.py tests/test_task_accept_correction.py
=> 31 passed in 13.34s
```

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-broad3 \
  tests/test_prefixed_ids.py tests/test_task_accept.py \
  tests/test_task_accept_correction.py \
  tests/test_task_accept_second_correction.py \
  tests/test_task_accept_recovery.py tests/test_task_accept_contracts.py \
  tests/test_event_outbox.py tests/test_mutation_tail.py \
  tests/test_direct_setup.py tests/test_task_terminal_guard.py \
  tests/test_tasks.py tests/test_validation.py tests/test_mcp_server.py \
  tests/mcp/test_external_conformance.py tests/test_distribution.py \
  tests/test_codex_plugin.py tests/test_skill_command_examples.py -rs
=> 315 passed, 2 skipped in 94.81s
```

The two skips are the pre-existing Linux-only `/proc` Direct Setup E2E and the
optional official MCP Python SDK import. No dependency was added.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-full -rs
=> 1490 passed, 2 skipped in 827.55s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
=> passed
```

The eight canonical M5 envelope goldens also recomputed to their approved byte
lengths and SHA-256 values without change.
