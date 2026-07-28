# 0221 P0-6 Execution Binding / Progress Receipt Validation

## Scope

- Goal: `G-0071`
- Task: `T-0148`
- Feature: `F-0077`
- Stories: `US-0076`–`US-0077` (`draft`)
- Tests: `TC-0168`–`TC-0173` (`planned`)

This slice records immutable target-bound execution progress without changing
Task or Goal lifecycle state. It adds `execution-binding/v1` and
`progress-receipt/v1`, stores each receipt as hash-anchored Evidence, and
projects only the newest target-bound receipt into resume and Task context.
It does not approve Stories, pass PCL Tests, migrate the database, add a
dependency, read or write Cockpit/CI state, or promote progress into verified
completion claims.

## Contract

- `pcl progress record` requires exactly one Task or Goal, a milestone, and a
  progress status (`started`, `completed`, or `blocked`).
- A blocked receipt requires at least one residual blocker.
- Canonical and execution roots must be the same worktree, linked worktrees
  with the same Git common directory, or the same non-Git root. Unrelated,
  missing, or mixed Git/non-Git roots fail closed.
- Cockpit and CI bindings are caller assertions only. Incomplete binding
  groups fail before mutation; PLH performs no external control-plane access.
- Optional latest Evidence must be healthy, terminal, and linked to the exact
  target.
- Receipt artifact bytes, Evidence row/link, and
  `progress_receipt_recorded` event are written as one mutation. The event
  anchors the artifact SHA-256, receipt ID, Evidence ID, and exact target.
- Resume and Task context select only the newest linked receipt. A corrupt,
  unanchored, or wrong-target newest receipt is surfaced as invalid and never
  falls back to an older receipt.
- Valid progress may orient summary, blockers, next action, and context refs,
  but it does not change `current_state`, Task/Goal status, or `verified`.
- With no receipt, existing resume and context JSON shapes remain unchanged.
  Progress fields are additive.
- The progress orientation section is required when a newest receipt exists
  and remains present under a tight context budget.

## Fail-first

```text
PYTHONPATH=src pytest -q tests/test_progress.py

10 failed in 7.79s
```

All failures were caused by the absent `progress` command. The suite covered
same-worktree and detached linked-worktree binding, malformed binding groups,
unrelated roots, wrong-target Evidence, no-receipt compatibility, resume and
tight-budget context projection, and corrupt-newest fail-closed selection.

## Green verification

```text
PYTHONPATH=src pytest -q tests/test_progress.py

10 passed in 6.92s
```

```text
PYTHONPATH=src pytest -q tests/test_resume.py

17 passed in 12.43s
```

```text
PYTHONPATH=src pytest -q tests/test_context.py

64 passed in 30.51s
```

```text
PYTHONPATH=src pytest -q tests/test_handoff_packet_contract.py \
  tests/test_contract_cli.py tests/test_progress.py

25 passed in 5.92s
```

The first full run found only two intentional public CLI expectation changes:
the top-level help snapshot and parser registration list did not yet include
`progress`. The canonical fixture generator updated only `pcl-help.json`, the
intended delta was recorded in the fixture README, and the focused rerun
passed 15 tests.

```text
PYTHONPATH=src pytest -q

1245 passed, 1 skipped in 983.40s (0:16:23)
```

```text
PYTHONPATH=src python -m ruff check .

All checks passed!
```

`git diff --check` passed.

## Repository dogfood

The current repository recorded progress for exact Task `T-0148`, with the
canonical repository as its execution root and Cockpit task `9a49ca29` as a
caller assertion:

```text
Evidence: E-0616
event: EV-16D96AD06743
artifact: .project-loop/evidence/progress-receipts/E-0616.json
artifact SHA-256: 8dc4f0a68fb1b40c002d8320be83d893cd64c05734fbac99cdbbc7e892caff12
receipt: pr-sha256:b1107150948f9d6d1cca9ca35843257966c686cd6c6107fd8764987806179da6
relationship: same_worktree
bound HEAD: 42a0a7ebed6c4452e9cb8ca67e250e9d6c03cf90
```

`pcl resume --target T-0148 --json` selected `E-0616` as current progress,
kept `current_state: IN_PROGRESS`, kept `verified: []`, and emitted a current
`progress-receipt/v1` context ref with the anchored SHA-256.

`pcl context pack --task T-0148 --max-tokens 350 --json` included both
`machine_context_rules` and required `progress_orientation`, with no required
section omitted.

```text
pcl contract validate --type progress-receipt/v1 \
  .project-loop/evidence/progress-receipts/E-0616.json --json

ok: true
errors: []
```

## PCL validation

Before dogfood, strict validation returned zero errors, three active and 26
historical advisories. The advisories pre-date this slice and were neither
normalized nor repaired.

## Residual boundaries

- Execution binding proves repository/worktree identity and caller-supplied
  control-plane identifiers; it does not prove which external process ran.
- Cockpit and CI bindings are passive receipt fields. Automatic reads, writes,
  or report synchronization remain outside PLH.
- The newest invalid receipt is intentionally sticky until a newer valid
  receipt is explicitly recorded.
- Progress is not a completion packet, verification result, Task state
  transition, or human Story approval.
- Story approval and PCL Test result transitions remain human-controlled.
