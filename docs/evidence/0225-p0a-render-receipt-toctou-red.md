# P0-A render receipt TOCTOU fail-first evidence

Date: 2026-07-30

Base commit:
`c82bc542e618008b99ece8faf1e65e8e09534100`

Command:

```text
PYTHONPATH=src pytest -q \
  tests/test_mutation_tail.py::test_render_receipt_captures_artifacts_before_final_watermark_check
```

Result:

```text
1 failed in 0.33s
```

The reproducer injects one normal `add_feature` service mutation plus a
dashboard render immediately before the first artifact receipt read. The old
implementation had already accepted equal pre/post watermarks, so it returned
`status=rendered`, `consistency=stable`, and `attempts=1` while hashing the
newer dashboard bytes.
