# 0153: Cross-skill integrity dogfood and release gate

- **Status:** Done locally; implementation, automated dogfood, and human review complete; not committed or released
- **Milestone:** v0.4.3 Evidence Completeness
- **Priority:** P0
- **Dependencies:** 0150, 0151, 0152
- **DB schema:** remains 8

## Problem

The contract is useful only if bundled Skill instructions and a real
cross-skill workflow cannot reproduce the LP dogfood false-completion path.

## Scope

- Add canonical incomplete-prototype and complete-deliverable fixtures.
- Re-run the LP-shaped flow or equivalent clean-room fixture with independent
  human review.
- Make all bundled `project-control-loop` Skill copies use parser-valid,
  Evidence-ID-first terminal examples.
- Explain that raw `--evidence` is a compatibility claim, not equivalent
  terminal proof.
- Verify exclusion warnings, policy mapping, unfinished routing, and approval
  provenance end to end.
- Prepare v0.4.3 release artifacts only after the human dogfood gate.

## Invariants

- Dogfood reports record failures and limitations, not only positive evidence.
- Prototype and complete results remain distinct.
- Package artifacts freeze only after full suite and clean-install smoke.
- Tag, push, GitHub Release, and PyPI are separate explicit operations.

## Non-scope

- The external mockup skill's Motion Phase, crop generator, detail inventory,
  or line-count repair.
- Publishing a release.

## Acceptance criteria

1. The incomplete fixture cannot pass a completion-required Test and leaves
   zero rejected-mutation traces.
2. The complete fixture can pass with a reviewable evidence/provenance chain.
3. `pcl next` never returns idle for the unfinished fixture.
4. All bundled Skill examples are exercised against the real parser.
5. Strict validation, full pytest, package/contract validation, and clean-wheel
   smoke pass.
6. Independent human review is given in conversation/Cockpit and recorded by
   the agent with distinct human-approver, agent-recorder, and source fields
   before release preparation; the human does not need to run `pcl`.
