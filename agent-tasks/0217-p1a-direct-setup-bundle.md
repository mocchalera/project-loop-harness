# 0217: P1-A Direct Setup Bundle

- **Status:** Independent review remediation implemented; re-verification pending
- **Milestone:** P1-A one-call setup and bounded mutation tail
- **Priority:** P1
- **Size:** L
- **Dependency:** P0-A mutation tail and P0-B Task terminal readiness
- **Project Loop:** Goal `G-0003`, Task `T-0003`, Feature `F-0003`, Stories
  `US-0003`–`US-0004`, Tests `TC-0020`–`TC-0024`
- **Schema/dependencies:** unchanged at schema 8 with no runtime dependency
- **Evidence:** `E-0017` / `docs/evidence/0233-p1a-direct-setup-red.md`,
  `E-0018` / `docs/evidence/0234-p1a-direct-setup-green.md`

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
review `bf15066b` later returned High 0 / Medium 5 / Low 2 and NO-GO. The
remediation binds spec/root/DB identity, serializes every canonical renderer
caller through one exclusive lock-aware wrapper, normalizes hostile parser
errors, uses full-SHA-256 new anchors with a verified legacy retry path, rejects
hardlinked specs, and adds exact resource-boundary tests. `E-0018` remains
immutable and must be superseded by current reproducible proof.

## Failure and recovery

- Parse, admission, collision, or pre-commit helper failure rolls the complete
  bundle back.
- After-commit projector failure returns exit 6 with no tail and recovers via
  `pcl audit flush --json`.
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
PYTHONPATH=src python -m pytest -q tests/test_start.py tests/test_mutation_tail.py tests/test_event_outbox.py tests/test_validation.py
PYTHONPATH=src python -m pytest
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m pcl start --help
git diff --check
```

All four Project Control Loop Skill copies are byte-identical. A fresh
initialized-project smoke covered success, exact retry, changed-input conflict,
strict validation, clean audit, and render. Exact results are recorded in
`docs/evidence/0234-p1a-direct-setup-green.md`.

## Stop conditions

Do not add a schema migration, dependency, telemetry, auth/billing behavior,
automatic Story approval, terminal Evidence acceptance, P1-C routing, external
write, push, deploy, publication, or Cockpit task lifecycle mutation.
