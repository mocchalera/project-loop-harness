# 0217: P1-A Direct Setup Bundle

- **Status:** Implemented locally; repository-wide verification pending
- **Milestone:** P1-A one-call setup and bounded mutation tail
- **Priority:** P1
- **Size:** L
- **Dependency:** P0-A mutation tail and P0-B Task terminal readiness
- **Project Loop:** Goal `G-0003`, Task `T-0003`, Feature `F-0003`, Stories
  `US-0003`–`US-0004`, Tests `TC-0020`–`TC-0024`
- **Schema/dependencies:** unchanged at schema 8 with no runtime dependency

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

The final design review reported High 0 / Medium 0. The user's final renderer
decision supersedes the earlier staged-publish proposal: use the current
renderer only after the exclusive-lock HWM recheck.

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

Also verify all four Project Control Loop Skill copies are byte-identical and
run a fresh initialized-project smoke test for success, exact retry, conflict,
strict validation, and render.

## Stop conditions

Do not add a schema migration, dependency, telemetry, auth/billing behavior,
automatic Story approval, terminal Evidence acceptance, P1-C routing, external
write, push, deploy, publication, or Cockpit task lifecycle mutation.
