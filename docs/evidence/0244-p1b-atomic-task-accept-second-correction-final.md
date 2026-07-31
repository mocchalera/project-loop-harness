# P1-B Atomic Task Accept second correction final evidence

## Scope and qualification

- bounded writer authority: independent fixed-hash re-review task `b59babf1`, report `seq2`
- correction base: `6bfa1c949e9e5e5b2dad0c167d31ac6414cb8bd0`
- first correction milestone: `c9029a88cf5440347edace4f22857ce1a96ebe91`
- schema: `8`; migrations: `0`; runtime dependencies added: `0`
- P1-C and hosted/cloud/telemetry/paid/external behavior: not implemented
- semantic boundary preserved: `US-0005=draft`, `T-0004=in_progress`, `F-0004=needs_test`

This immutable Evidence qualifies `E-0051` and
`docs/evidence/0243-p1b-atomic-task-accept-second-correction.md`. A final
self-review found that its M2 physical timing still published the projection
record before SQLite commit and deferred the accepted record until the end of
the tail. The approved seq27/seq28 accounting requires the opposite boundary:
24 prepared records before commit, the accepted authority immediately after a
confirmed SQLite commit, and the six projection/render/teardown/tail/seal
records only after their authorities succeed. This document records that
bounded correction. It is implementation Evidence, not independent
acceptance.

## Additional fail-first record

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-timing-red \
  tests/test_task_accept_second_correction.py::test_projection_failure_has_committed_accepted_authority_before_projection
=> 1 failed in 0.86s
=> observed 25 records, accepted=0, projection=1
```

The fixed test requires the approved committed pre-tail state:

```text
records=25
accepted=1
projection=render=teardown=tail=generation-manifest=ledger-sealed=0
```

## Corrected authority timing

- `MutationConnection.commit` executes the retained no-follow proof seal,
  commits SQLite, publishes the single accepted authority, and only then enters
  the projector. The accepted publisher is unavailable before commit.
- The crash point `after_sqlite_commit_before_projector` is after accepted
  publication, so real abrupt recovery begins from the canonical 25-record
  committed pre-tail state.
- Projection failure therefore returns `mutation_committed=true`, exit 6, and
  exactly the approved 25-record accounting. Dedicated audit recovery reruns
  live strict validation and P0-B readiness before publishing the remaining
  five live records plus one sealed ledger head.
- Commit acknowledgement loss remains distinct. If a synthetic lost-ack path
  bypasses the postcommit publisher, recovery recognizes the 24-record state,
  confirms DB authority, publishes accepted once, and then publishes the six
  normal recovery records. It is never treated as exact replay or a safe
  original-request retry.
- Exact replay continues to require the complete 31-record reserved-to-sealed
  generation and produces zero for all 25 effects.

## Final source hashes

```text
src/pcl/task_accept.py
194987f5c560c47dc81e83c0091eb8bbba911c1391f2462d1ea6994023559f94
src/pcl/db.py
888e0ee75058b6c7c6e67728899adc18525936a98b0df6afa46cbb927ca4e633
tests/test_task_accept_second_correction.py
021a30819753a981f621758d01e0cc0efae4482b35a9aaa0824919f614a543ac
tests/test_task_accept_recovery.py
d8876f8c845c82de2c000292761a01029571a08c7822660179306f32293b4552
tests/fixtures/task_accept_m2_record_contents_v1.json
c1530c086ddde65e6a13cff7cb6d846cf6fbb82213770b5307bcfbbc510b9c92
```

The fixed authority fixture is 27,075 repository bytes including one terminal
LF. Removing that LF yields the approved 27,074 bytes and SHA-256
`07e41045a685aac088ae6323352f8c5d5ecd2173a56fd1e2c23e49c878c64b0b`.

## Final verification

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-timing-green2 \
  tests/test_task_accept_second_correction.py::test_projection_failure_has_committed_accepted_authority_before_projection \
  tests/test_task_accept_recovery.py::test_postcommit_projection_failure_uses_dedicated_tail_recovery_generation \
  tests/test_task_accept_recovery.py::test_abrupt_postcommit_crash_recovers_tail_without_business_reexecution \
  tests/test_task_accept_recovery.py::test_commit_outcome_unknown_is_never_success_or_safe_original_retry
=> 4 passed in 3.88s
```

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-broad6 \
  tests/test_prefixed_ids.py tests/test_task_accept.py \
  tests/test_task_accept_correction.py tests/test_task_accept_second_correction.py \
  tests/test_task_accept_recovery.py tests/test_task_accept_contracts.py \
  tests/test_event_outbox.py tests/test_mutation_tail.py tests/test_direct_setup.py \
  tests/test_task_terminal_guard.py tests/test_tasks.py tests/test_validation.py \
  tests/test_mcp_server.py tests/mcp/test_external_conformance.py \
  tests/test_distribution.py tests/test_codex_plugin.py \
  tests/test_skill_command_examples.py -rs
=> 316 passed, 2 skipped in 124.11s
```

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-full2 -rs
=> 1491 passed, 2 skipped in 684.50s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
=> passed
```

The skips are the pre-existing optional official MCP SDK import and the
Linux-only `/proc` Direct Setup E2E. No dependency was added to remove either
skip.

