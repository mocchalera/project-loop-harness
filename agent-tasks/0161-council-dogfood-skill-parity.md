# 0161: Council dogfood, Skill parity, and operator documentation

- **Status:** Planned; paid/network work remains human-gated
- **Milestone:** v0.5.0 Council Profile
- **Priority:** P1
- **Size:** L
- **Dependencies:** 0160; separately approved compatible runner or manual bundle
- **DB schema:** no change

## Goal

Exercise the frozen boundary on real repository work and align CLI, Skill,
operator docs, and handoff behavior without hiding approvals or failure cases.

## Scope

- Dogfood one ambiguous and one high-risk task in approved repositories.
- Include one intentional partial/budget/error safe-stop.
- Measure human review time, decision count, bytes, schema corrections, cost,
  latency, and rework.
- Verify Brief revision/approval, implementation, finish, and resume retain
  Council Evidence references.
- Update README/adoption/Skill guidance and run cross-skill parity checks.

## Invariants

- Real provider use needs a hash-bound human approval naming budget and data.
- No production data, secret, credential, or full transcript enters artifacts.
- Agreement is not proof and Direct remains the clear-task default.
- Dogfood does not default-enable or publish the Profile.

## Acceptance

1. Two reviewed dogfood packets and one safe-stop packet exist as Evidence.
2. Secret scans of request/bundle/event artifacts are clean.
3. Skill/CLI/docs commands are parser-valid and behaviorally aligned.
4. A concrete adopt/modify/continue/reject recommendation is ready for 0162.
5. Strict validation and full tests pass.

