# P0-A render receipt TOCTOU follow-up validation

Date: 2026-07-30

Base commit:
`c82bc542e618008b99ece8faf1e65e8e09534100`

## Fail-first

Evidence `E-0009` pins the focused reproducer:

```text
1 failed in 0.33s
```

The old ordering accepted a stable final watermark before artifact receipt
bytes were read, so the injected service mutation and render escaped the
bounded consistency check.

## Fix

Each render attempt now performs these operations in order:

```text
pre-render high-watermark
render
HTML bytes/hash/size
dashboard-data bytes/hash/size
final high-watermark
```

The captured receipts are returned only when the final watermark equals the
pre-render watermark. Otherwise both captured receipts are discarded and the
existing fixed two-attempt loop retries or fails closed.

## Verification

Focused reproducer:

```text
1 passed in 0.35s
```

P0-A focused, validation, mutation, Task, and Feature suites:

```text
65 passed in 6.93s
```

Full suite:

```text
1287 passed, 1 skipped in 274.17s (0:04:34)
```

Static checks:

```text
ruff check .: passed
git diff --check: passed
```

Fresh isolated concurrency smoke:

```text
root:
  /tmp/pcl-p0a-receipt-toctou-20260730.SBDmQA
status:
  rendered
attempts:
  2
state high-watermark:
  15
original feature_added event count:
  1
HTML SHA-256:
  9b7479becca7fcd0098863967dd2269b3ad6be29415c0dd13a04b714b7f155e0
dashboard-data SHA-256:
  9b1111bc63f247009f6271e7a20cb21510c070c6e370f5b3e1d9a7ddbd35071e
```

The smoke injected a normal `add_feature` service mutation and dashboard
render immediately before the first artifact receipt capture. The first
capture was discarded, the second attempt converged at sequence 15, both
reported hashes matched the final artifact bytes, and the original Feature
event was not duplicated.

## Residual boundary

No schema migration, dependency, telemetry, P0-B behavior, external write, or
push was introduced.

The two review Low findings remain unresolved:

- a `changed=false` tail failure can still have conflicting stderr/retry
  diagnostics;
- real ENOSPC/EACCES and a failure between the two artifact writes remain
  covered only by injected `OSError`.

The task-local Story remains draft because the approval CLI cannot record the
required human approval provenance. Test `TC-0013` therefore retains its
fail-first state; this artifact records current GREEN implementation evidence
without fabricating semantic approval.
