# 0217: P1-A Direct Setup Bundle

- **Status:** Second independent rereview remediation implemented and re-verified
- **Milestone:** P1-A one-call setup and bounded mutation tail
- **Priority:** P1
- **Size:** L
- **Dependency:** P0-A mutation tail and P0-B Task terminal readiness
- **Project Loop:** Goal `G-0003`, Task `T-0003`, Feature `F-0003`, Stories
  `US-0003`–`US-0004`, Tests `TC-0020`–`TC-0024`
- **Schema/dependencies:** unchanged at schema 8 with no runtime dependency
- **Evidence:** fail-first `E-0017`; superseded proofs `E-0018` and `E-0019`;
  second-review RED `E-0025`; current proof `E-0029`; exact-target Test
  Evidence Sets `E-0030`–`E-0034`

## Approved contract

The final design and independent review fixed these boundaries:

1. `pcl start "<intent>" --direct-spec <project-relative-path> --json` is the
   one-call public surface in an initialized project.
2. A strict, descriptor-bound `direct-spec/v1` creates one Goal, Task, Feature,
   one or more draft Stories, one or more planned Tests, and only the existing
   start receipt Evidence.
3. One `BEGIN IMMEDIATE` transaction performs DB-authoritative admission and
   appends exactly `6 + S + T` events with one outbox row per event.
4. Schema-8 idempotency uses a request-derived deterministic `work_started`
   event primary key. The existing `start-receipt/v1` fields remain compatible;
   Direct data is additive under `receipt.direct_setup`.
5. The tail performs at most two validation/routing consistency attempts.
   Canonical dashboard files are untouched during those reads. Under the
   existing exclusive project-operation lock, a matching HWM permits at most
   one call to the current canonical renderer.
6. No two-file/process-crash dashboard atomicity, Story approval, P1-B terminal
   acceptance, or P1-C Skill router is claimed.

The initial design review reported High 0 / Medium 0. Independent implementation
review `bf15066b` later returned High 0 / Medium 5 / Low 2 and NO-GO. At
`884010a9c7366c01f956d5256b52f34d1b3787cb`, the
remediation binds spec/root/DB identity, serializes every canonical renderer
caller through one exclusive lock-aware wrapper, normalizes hostile parser
errors, uses full-SHA-256 new anchors with a verified legacy retry path, rejects
hardlinked specs, and adds exact resource-boundary tests.

The second rereview of
`b54340e19f7a39cb65e5bf9106db0dfe645f6415` returned High 1 / Medium 3 /
new Low 0 and NO-GO. At
`dfc55144732a6e6a121868ffe7be5984bdbed57a`, the retained root capability
now remains authoritative through SQLite commit, projection, and tail;
descriptor-bound Git inherits the verified FD; the private renderer route
requires a live same-root exclusive capability; and legacy retries reject
actual same-request ambiguity. `E-0018`, `E-0019`, their sources, and their
durable copies remain immutable. `E-0029` supersedes `E-0019` with current
proof.

## Failure and recovery

- Parse, admission, collision, or pre-commit helper failure rolls the complete
  bundle back.
- After-commit projector or retained-root diagnostic failure returns exit 6
  with `mutation_committed: true`, `safe_to_retry_original: false`, and no
  tail; recover via `pcl audit flush --json`.
- Exact retries are no-ops; changed input, ambiguous/corrupt anchor state, or
  inconsistent receipts fail closed.
- Stable validation failure is partial, skips routing/render, returns no
  artifact hashes, and uses exact-target read-only validation recovery.
- A second HWM drift is partial and does not render. Renderer failure returns
  no success hashes.

## Verification boundary

Use worktree source directly:

```text
PYTHONPATH=src python -m pytest -q tests/test_direct_setup.py
PYTHONPATH=src python -m pytest -q tests/test_direct_setup.py tests/test_render_lock.py tests/test_mutation_tail.py tests/test_start.py tests/test_event_outbox.py tests/test_mcp_server.py tests/test_dashboard.py tests/test_workflow_executor.py tests/test_workflows.py tests/test_workflow_proposals.py tests/test_locks.py tests/test_validation.py tests/test_command_guide.py tests/test_cli_init.py
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m pcl start --help
git diff --check
```

The exact focused result is `260 passed, 1 skipped in 28.02s`; the full result
is `1382 passed, 2 skipped in 327.85s`; Ruff passes. The skips are the
Linux-only Direct Git E2E on the Darwin verification host and the prohibited
optional MCP SDK. The portable production POSIX Git subprocess regression
passes. External MCP conformance is `8 passed, 1 skipped in 0.88s`.

All four Project Control Loop Skill copies are byte-identical. A fresh
initialized-project smoke covered success, exact retry, changed-input conflict,
stored Git revision, strict validation, clean audit, and render. Exact results
are recorded in
`docs/evidence/0237-p1a-retained-capability-remediation-green.md`.

`TC-0020`–`TC-0024` each pass a target-bound completion policy through
`E-0030`–`E-0034`; `F-0003` and `T-0003` are done. Strict doctor/validate and
the audit scoped to `T-0003` since `EV-E71D510409F1` are clean. The root audit
continues to report only the separately known superseded historical drift for
`E-0013` and `E-0014`.

## Stop conditions

Do not add a schema migration, dependency, telemetry, auth/billing behavior,
automatic Story approval, terminal Evidence acceptance, P1-C routing, external
write, push, deploy, publication, or Cockpit task lifecycle mutation.
