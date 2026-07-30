# P0-B Task terminal readiness GREEN evidence

Date: 2026-07-30

## Independent-review correction

This evidence is not the final provenance claim. Independent review at
`7de0c7c49065cffba8ff45ef50d8cdd02e802c0a` proved that the implementation
caught an uncoordinated copied-byte drift but did **not** bind a coherently
rewritten manifest/copy or Evidence Set artifact to its immutable recording
event. The statement below that event-free current Evidence drift was covered
was therefore too broad. See
`0229-p0b-strict-proof-review-red.md` and the subsequent remediation GREEN
evidence for the corrected contract and results.

Base:
`c923a1eb5ef6360896c72dfa00570798cc8c9c21`

Implementation commit:
`b133aba42d5e6ae2dea0608dc7c01ad059bc09c5`

## RED to GREEN

The fail-first slice at the base commit produced:

```text
4 failed, 1 passed in 1.12s
```

It reproduced unsafe direct Task completion, failure-path mutation/tail work,
missing success receipts, and success-shaped text output. The same-state
characterization passed.

After implementation, the focused evaluator/direct/finish suite produced:

```text
73 passed in 29.62s
```

Coverage includes deterministic order/dedupe/digest, unknown fail-closed,
dependencies, Feature/Story/Test/Defect, standalone Task compatibility, Goal
status/budget/Decision, acceptance Evidence type/target/supersession/hash
drift, Evidence Set/completion receipt, Workflow Goal/Run/Jobs/Verification,
current versus historical proof, exact/global/human findings, zero-mutation,
same-state, parallel done, dependent-state serialization, surface digest
parity, and finish HWM/input freshness rollback.

## Full verification

```text
PYTHONPATH=src pytest -q
1315 passed, 1 skipped in 276.54s (0:04:36)

PYTHONPATH=src python -m ruff check .
All checks passed!

git diff --check
passed

PYTHONPATH=src python -m pcl --help
exit 0
```

The first full run exposed one additive baseline-fixture normalization gap:

```text
1 failed, 1314 passed, 1 skipped in 296.51s (0:04:56)
```

The generated snapshot contained the new receipt's random event ID. The
fixture normalizer now replaces event IDs with a deterministic placeholder,
the existing `related_goal_status` key remains intact, and the intended
additive receipt snapshot is committed. The final full run above is the
post-fix result.

## Contract evidence

- Direct Task `done` resolves and re-reads the exact Task inside the existing
  `BEGIN IMMEDIATE`, then evaluates one `terminal-readiness/v1` receipt before
  the update.
- Failure is typed `task_terminal_readiness_failed`, exit 1, and byte-for-byte
  zero-mutation across Task/event/outbox/JSONL/dashboard artifacts. It does not
  invoke `mutation-tail/v1`.
- Success commits one Task update and one status event/outbox pair. Result and
  event contain the same receipt; the P0-A tail starts post-commit.
- An already-done same-state request remains `changed=false` with no preflight,
  event, or render.
- Read/list/next/direct expose one canonical digest and event HWM for the same
  snapshot.
- Task-bound finish rechecks Task/HWM/input/current proof inside the final
  transaction. At this revision, an intervening PCL event and uncoordinated
  current Evidence byte drift returned `finish_target_readiness_changed`;
  coherent manifest/artifact substitution remained an independent-review
  defect and is not claimed as covered by this evidence.
- Normal failed-check attempt/packet semantics, exit compatibility, and P0-A
  post-commit failure semantics remain covered by the full suite.
- Four loaded/distributed Skill copies are byte-identical at SHA-256
  `1f13620752c71284df06cf99e8ba5e083fb8ed1f4a55220f6a72b8bea918c2c2`;
  the three canonical distribution copies are a byte-identical subset.

## Preserved boundaries

No schema migration, dependency, telemetry, force/override, automatic human
approval, external operation, push, main-checkout change, Task completion, or
Task removal was introduced.

The pre-existing P0-A Low boundaries remain separate and unchanged:

1. mutable artifact-path overwrite timing after final HWM needs clearer
   contract wording;
2. a `changed=false` tail failure can retain conflicting stderr/retry
   diagnostics;
3. real ENOSPC/EACCES and a failure between two artifact writes remain covered
   by injected failures rather than OS-level reproduction.

Story `US-0002` remains draft and Tests `TC-0014`–`TC-0016` remain planned.
Implementation authority and Cockpit Ask decisions were not fabricated as
Story-approval provenance.
