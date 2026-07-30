# P1-A retained-capability independent-review RED

Date: 2026-07-30

## Review authority

- Independent READ-ONLY re-review: `bf15066b`
- Reviewed HEAD: `b54340e19f7a39cb65e5bf9106db0dfe645f6415`
- Verdict: High 1 / Medium 3 / new Low 0, NO-GO
- `E-0018`, `E-0019`, and `E-0020`–`E-0024` remain immutable.
- `E-0019` is byte-healthy but does not detect the findings below, so it is no
  longer semantic completion authority for P1-A.

## Fail-first command

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_direct_setup.py::test_direct_setup_root_capability_spans_commit_projection_and_tail \
  tests/test_direct_setup.py::test_direct_spec_root_fd_resolves_git_revision_after_rename \
  tests/test_direct_setup.py::test_direct_setup_git_revision_linux_e2e \
  tests/test_direct_setup.py::test_direct_setup_postcommit_projection_failure_is_typed_committed \
  tests/test_direct_setup.py::test_direct_setup_legacy_retry_rejects_same_request_ambiguity \
  tests/test_render_lock.py::test_public_renderer_blocks_on_another_process_exclusive_lock \
  tests/test_render_lock.py::test_lock_held_renderer_requires_live_matching_capability
```

Exact result:

```text
7 failed, 3 passed, 1 skipped in 2.94s
```

The Linux E2E case was skipped because this run is on Darwin. The portable
POSIX Git/FD subprocess case ran and failed because the retained binding did
not yet expose descriptor-bound revision resolution.

## Observed RED boundaries

1. Root replacement after the final pre-commit identity check produced exit 4
   after authoritative state had committed to the displaced root.
2. Root replacement immediately after SQLite commit and before projection
   produced exit 2 instead of a committed/recoverable result.
3. Root replacement after projection and before the tail produced exit 2.
4. A retained root binding had no descriptor-bound Git revision method.
5. A post-commit projection failure returned exit 6 but omitted explicit
   `mutation_committed: true` and `safe_to_retry_original: false`.
6. A legacy 48-bit anchor plus a second same-request `work_started` event was
   incorrectly accepted as `already_started`.
7. The renderer had no live, root-matching exclusive-lock capability route;
   the public boolean bypass remained available.

The two earlier barriers, before and immediately after DB connection, already
failed closed with no bundle in either root. A public renderer in another
process also correctly blocked on the exclusive lock. Those passing controls
are retained in the remediation suite.
