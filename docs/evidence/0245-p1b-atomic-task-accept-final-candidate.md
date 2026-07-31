# P1-B Atomic Task Accept final candidate evidence

## Scope and lineage

- bounded writer authority: independent re-review `b59babf1`, report `seq2`
- base: `6bfa1c949e9e5e5b2dad0c167d31ac6414cb8bd0`
- first verified milestone: `c9029a88cf5440347edace4f22857ce1a96ebe91`
- schema `8`, migrations `0`, runtime dependencies added `0`
- no P1-C, hosted/cloud/telemetry/paid/external behavior
- preserved state: `US-0005=draft`, `T-0004=in_progress`, `F-0004=needs_test`

This Evidence supersedes the implementation claim in `E-0052` without
overwriting its immutable source or copy. After `E-0052` was recorded, final
self-review found one additional M2/M5 accounting edge: failure to publish the
postcommit accepted record left 24 physical records but reported the canonical
projection-failure count of 25. The final candidate now keeps this distinct
from the normal 25-record projection-failure state.

## Final authority behavior

- Before SQLite commit, 24 canonical records exist: 14 reservation-index, nine
  prepared live records, and one reserved ledger entry.
- Immediately after confirmed SQLite commit, accepted publication produces the
  canonical 25-record committed pre-tail state. Projection remains unpublished
  until projector/render authority succeeds.
- Normal projection failure reports 25 actual records and recovers by
  publishing five live tail records plus one sealed ledger record.
- Accepted-publication failure reports 24 actual records,
  `mutation_committed=true`, exit 6, and `process_restart_and_inspect`.
  Dedicated recovery confirms DB authority and live strict/P0-B readiness,
  publishes accepted once plus the normal six-record tail, then permits only
  exact all-zero replay.
- A complete two-Test fresh success is 31 records; exact replay publishes zero
  records and all 25 effects are zero.
- H1 retained no-follow manifest/member/root descriptors still span the final
  reseal through SQLite commit. M3 supporting Evidence and M4 live recovery
  readiness closures remain unchanged.

## Additional RED to GREEN

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-publish-red \
  tests/test_task_accept_second_correction.py::test_postcommit_accepted_publish_failure_reports_actual_24_record_state
=> 1 failed in 0.83s
=> divergent result: task_accept_projection_pending with 25 reported effects

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-publish-recovery \
  tests/test_task_accept_second_correction.py::test_postcommit_accepted_publish_failure_reports_actual_24_record_state
=> 1 passed in 0.59s
```

The GREEN case verifies the 24-record state, seven-record dedicated repair,
and subsequent exact replay success.

## Final source hashes

```text
src/pcl/task_accept.py
1f5e29ac0debf368a4799d11067654e73c9971f4daca645061ea33c3376ed36e
src/pcl/db.py
888e0ee75058b6c7c6e67728899adc18525936a98b0df6afa46cbb927ca4e633
tests/test_task_accept_second_correction.py
46aa67a71c03b36bfc5ed4799409f2dcd46d76fa3fb2e5ef67b2f5e5de2772e9
tests/test_task_accept_recovery.py
d8876f8c845c82de2c000292761a01029571a08c7822660179306f32293b4552
tests/fixtures/task_accept_m2_record_contents_v1.json
c1530c086ddde65e6a13cff7cb6d846cf6fbb82213770b5307bcfbbc510b9c92
```

The fixture is 27,075 repository bytes with its terminal LF. Without that LF,
the approved canonical identity is 27,074 bytes and SHA-256
`07e41045a685aac088ae6323352f8c5d5ecd2173a56fd1e2c23e49c878c64b0b`.

## Final verification

```text
focused Task Accept/MCP suite
=> 116 passed, 1 skipped in 37.59s

high-risk P0-B/P1-A/mutation-tail/MCP/Skill/prefixed-ID suite
=> 317 passed, 2 skipped in 126.52s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests pytest -q \
  -p no:cacheprovider --basetemp=/tmp/plh-p1b-second-full-final -rs
=> 1492 passed, 2 skipped in 874.29s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
=> passed
```

The skips remain the optional official MCP SDK import and Linux-only `/proc`
Direct Setup E2E. No dependency was added. Independent fixed-hash READ-ONLY
review remains the acceptance authority.

