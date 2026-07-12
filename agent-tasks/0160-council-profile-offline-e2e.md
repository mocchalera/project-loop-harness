# 0160: Council Discovery built-in Profile and offline E2E

- **Status:** Done
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P1
- **Size:** M
- **Dependencies:** 0159
- **DB schema:** no change

## Goal

Prove the complete Core boundary without a provider, API key, paid service, or
network access.

## Scope

- Finalize built-in `council.discovery` manifest and deterministic offline
  fixture runner/test helper.
- Cover completed, needs-human, partial, budget-exhausted, failed, skipped, and
  malformed cases.
- Document prepare -> fixture run -> dry-run -> ingest -> next -> select ->
  separate Brief revision/review/approval.
- Add a human-readable 30-second Decision projection fixture.
- Run source, wheel, and extracted-sdist E2E.
- Include a bypass regression proving plain `decision resolve/waive` cannot
  close a proposal-linked gate.

## Invariants

- Fixture runner cannot mutate PLH state and does not ship provider code.
- Outputs are byte-deterministic.
- Council output is Evidence, not fact, approval, or verification.
- Direct path remains unchanged and Profile use remains opt-in.

## Acceptance

1. All statuses produce their documented safe next action.
2. needs-human opens and resolves a real existing Decision.
3. budget/partial/failed never become execution-ready.
4. All package environments contain required schemas/manifest/fixtures.
5. Full compatibility and distribution suites pass.

## Implementation evidence

- `pcl profile fixture-run` produces deterministic provider-free output for
  completed, needs-human, partial, budget-exhausted, failed, skipped, and
  malformed scenarios without reading or mutating PLH state.
- The packaged fixture descriptor and runtime contain no provider/API code.
- One reusable E2E script proves prepare → two byte-identical fixture runs →
  dry-run → ingest, and for needs-human: next → legacy bypass rejection →
  proposal show/select → separate Brief revision/review/approval.
- A 30-second Decision projection fixture defines the minimum factual fields
  and safe command surface.
- The same E2E script passes from source, an installed wheel, and an extracted
  sdist.
- Verification: targeted E2E/distribution/Profile suite 65 passed; full suite
  935 passed, 1 skipped.
