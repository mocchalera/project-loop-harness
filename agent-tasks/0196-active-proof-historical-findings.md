# 0196: Active Proof / Historical Findings Separation

- **Status:** Complete
- **Milestone:** Harness Minimization Phase 3
- **Priority:** P0
- **Size:** M
- **Dependency:** 0192 audit evidence-impact classification; 0193 routing
- **DB schema:** remains 8 unless a separate human-approved design proves otherwise

## Problem

Strict validation can be green while returning many warnings about closed,
waived, or superseded history. Those findings are useful audit records, but a
flat list makes them look like current acceptance blockers and encourages more
procedural prose telling agents how to reinterpret the output.

## Scope

1. Characterize every current structured finding family and the entity status
   information available for deterministic classification.
2. Add the smallest additive machine contract that distinguishes findings
   affecting current proof from findings retained as historical record.
3. Default unknown or unclassifiable findings to the active/current side.
4. Preserve `ok`, errors, warnings, exit codes, finding codes, ordering, and
   repair commands.
5. Surface deterministic counts in JSON and validation reports without hiding
   either class.

## Acceptance

1. Active broken proof is never downgraded or hidden.
2. Closed/waived/superseded historical gaps are distinguishable without
   parsing English messages.
3. Existing callers that only consume `ok`, `errors`, `warnings`, or `findings`
   remain compatible.
4. The repository's current strict validation explains its historical warning
   count separately from current proof findings.
5. No schema migration or dependency addition; targeted/full tests and a
   current-repository dogfood report pass.

## Design gate

Before editing runtime code, produce a short responsibility map and prove that
classification can be derived from durable entity state. If a finding family
requires semantic inference from prose or user intent, leave it active and
record that limitation rather than encoding a guess.
