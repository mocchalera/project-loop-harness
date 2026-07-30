# P1-A third independent review RED

## Boundary

- Reviewed source HEAD:
  `86b0f0f6e37ff4c12f1cdee3593c005dfbacb1c4`
- Independent reviewer task: `bf15066b`
- Verdict: NO-GO after two production attacks
- Immutable prior authority: `E-0018`, `E-0019`, `E-0020`–`E-0024`,
  `E-0029`, and `E-0030`–`E-0034`
- The semantic NO-GO transition and failing Tests remain recorded by immutable
  `E-0035`–`E-0038`.

## Fail-first command

```text
PYTHONPATH=src python -m pytest -q \
  tests/test_direct_setup.py::test_direct_setup_root_capability_spans_tail_production_boundaries \
  tests/test_direct_setup.py::test_direct_setup_tail_read_only_db_open_cannot_rebind_resolved_path \
  tests/test_direct_setup.py::test_direct_setup_changed_false_tail_exception_is_exit6_bound_partial \
  tests/test_render_lock.py::test_lock_held_renderer_rejects_root_aba_and_replaced_lock_file \
  tests/test_render_lock.py::test_lock_held_renderer_accepts_same_root_identity_after_rename \
  tests/test_render_lock.py::test_private_capability_constructor_cannot_forge_live_ownership \
  tests/test_render_lock.py::test_reacquired_lock_rejects_reused_expired_capability
```

Observed on the reviewed source:

```text
12 failed, 2 passed in 3.20s
```

## Reproduced failures

1. Every exercised Direct tail production boundary still returned
   `safe_to_retry_original: true` for a committed request. A stable validation
   partial also returned exit 0 rather than exit 6.
2. The common read-only SQLite helper called `db_path.resolve()` before opening
   the URI. A root swap between URI construction and SQLite open could rebind
   the tail read to the replacement pathname.
3. An idempotent `changed=false` tail exception escaped the Direct result rather
   than returning a typed exit-6 partial with `mutation_committed: false`.
4. A token issued for root A was accepted after root ABA when A's loop
   directory was moved under replacement root B and `project.lock` was replaced.
   A real spawned process simultaneously acquired and held B's new lock file.
5. Importing the private capability class and replacing the issuer's token
   allowed a forged live token to reach the private renderer.

The positive controls passed: same-root rename retained the correct target
identity, and an expired capability remained rejected after lock
reacquisition.

## Required closure

- Preserve the retained descriptor/file-ID DB path without `resolve()` or
  `realpath()`.
- Never claim that the original pathname is a safe retry authority.
- Return every Direct partial or unexpected tail exception as exit 6, with
  `mutation_committed` distinguishing changed and idempotent calls.
- Emit only a command-null exact-target recovery plan bound to the retained
  root device/inode.
- Bind the private renderer token to root, loop directory, open lock-file
  identity, issuing process/thread, and a live registry entry.
- Reject root/path ABA, replaced lock files, forged, boolean, expired, reused,
  non-owner, another-root, and fake tokens while preserving same-root rename
  and non-reentrant Direct rendering.
