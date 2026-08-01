# P1-B revised-linearization correction evidence

## Authority and scope

- human authority: `ask_cb3c43a0cbd2`
- correction base: `48c00b504c2ebac75f9014d706a61cb582799b6e`
- scope: P1-B post-reseal tamper classification only; no P1-C
- schema `8`, migrations `0`, runtime dependencies added `0`
- preserved semantic boundary: `US-0005=draft`, `T-0004=in_progress`,
  `F-0004=needs_test`, `TC-0025`–`TC-0028=planned`

This Evidence qualifies and supersedes the implementation claim in `E-0053`.
It does not overwrite the `E-0053` source or copy and is not independent
acceptance.

## Revised contract

The successful final retained-descriptor reseal is filesystem current-proof
linearization point V, conditional on the staged SQLite transaction committing.
It does not claim pathname currentness through physical SQLite commit.

- Pre-V manifest/member/root drift remains an effect-zero rollback.
- Descriptors remain retained through physical commit.
- The first post-commit callback runs before accepted authority, projection,
  render, or tail publication.
- A change observed there returns exit 6,
  `task_accept_post_acceptance_corruption`, phase
  `post_acceptance_corruption`, with committed business state and the canonical
  24-record pending authority; accepted/projection/render/sealed-tail records
  remain unpublished.
- A second live check after projection isolates later corruption before render
  with the 25-record accepted pre-tail authority.
- Later corruption is detected by validation, doctor, readiness, replay, and
  tail recovery. Recovery does not overwrite or adopt corrupt Evidence.

## Fail-first RED

The first invocation used `/usr/local/bin/python3`, which had no pytest module;
it collected zero tests and is setup failure, not RED.

Authentic RED:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest -q \
  -p no:cacheprovider \
  --basetemp=/tmp/plh-p1b-linearization-red-authentic \
  tests/test_task_accept_linearization.py
=> 3 failed in 0.99s
```

Both external-process variants synchronized on the
`MutationConnection.commit` line event for `super().commit()` after the product
guard returned. In-place truncate/rewrite and rename replacement both returned
the old false `ok=true` success. The third RED showed copied-member corruption
as a warning rather than an integrity error.

## GREEN and adversarial results

```text
targeted revised-linearization suite
=> 3 passed in 1.09s

focused Task Accept, M1/M2/M3/M4, recovery, MCP suite
=> 111 passed in 12.48s

high-risk P0-B/P1-A/mutation-tail/outbox/Evidence/validation/next/finish/
prefixed-ID/MCP/Skill suite
=> 346 passed, 2 skipped in 97.96s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m pytest -q \
  -p no:cacheprovider \
  --basetemp=/tmp/plh-p1b-linearization-full-final -rs
=> 1495 passed, 2 skipped in 349.64s

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
=> passed
```

The skips are the optional official MCP Python SDK import and Linux-only
`/proc` Direct Setup root-capability E2E. The clean path continues to match the
frozen seq27 31-record fixture SHA
`07e41045a685aac088ae6323352f8c5d5ecd2173a56fd1e2c23e49c878c64b0b`,
and the eight seq28 semantic envelope goldens remain byte-exact.

The adversarial tests additionally establish:

- immediate post-V corruption commits Test/Feature/Task business state but
  leaves all six outbox rows pending and publishes no accepted or sealed tail;
- explicit `pcl audit flush --json` projects committed events but returns the
  fixed blocked recovery envelope and publishes no healthy tail record;
- post-immediate-check corruption blocks strict and non-strict validation,
  doctor, terminal readiness, exact replay, render, and tail recovery;
- validate and doctor preserve DB counts, events JSONL, dashboard data, and
  dashboard HTML bytes;
- recovery leaves the corrupt copied member byte-identical and creates no
  replacement Evidence.

## Candidate source hashes

```text
src/pcl/db.py
7a6c7dc8d3098e7c4d6f29ab1708b2e3e7c68c5f6d366bb636b05c0bb6bd37d0
src/pcl/task_accept.py
ece0a4588ac37c76c0bd5818dd245bfc01fcd605d083352b05bd47a2aac08b52
src/pcl/validators.py
0bae60be6313f2b35b3f7f1ae79bd5ab43310cb46cebc47af164148d054b72ea
tests/test_task_accept_linearization.py
1e170f2a6e466dae1958ee2efec88cb34894247099ccea6561b53734466ec257
```

These hashes were captured before the final documentation-only qualification;
the final commit hash is reported separately in the writer handoff.

## PCL validation

Before this Evidence mutation:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pcl --root . \
  validate --strict --json
=> ok=true; active findings 0; historical findings 0
```

The repository-local Story remains draft by design. This correction neither
approves/waives `US-0005` nor terminalizes `F-0004` or `T-0004`.
