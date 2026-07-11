# 0152: Next-action and approval-provenance integrity

- **Status:** Done locally; verified; not committed
- **Milestone:** v0.4.3 Evidence Completeness
- **Priority:** P0
- **Dependencies:** 0151
- **DB schema:** remain 8; stop for human approval if a migration is needed

## Problem

LP dogfood reached a neutral idle route while its Feature was only `passing`
and its domain verdict was incomplete. Agent self-review and explicit human
approval also need visibly different authority.

## Scope

- Route `passing` but not `done` Features to a factual next action.
- Route missing/incomplete required completion verdicts ahead of idle.
- Add schema-8 event/Evidence receipts exposing `actor_kind`, factual actor
  identity when available, source, timestamp, target, and bound hash.
- Keep human-gated transitions unresolved unless provenance is human-origin.
- Surface provenance and blockers in JSON, resume/context, and dashboard data
  without turning the dashboard into state.
- Treat conversation/Cockpit approval as the normal human UX: an agent may
  record it later, but the receipt must distinguish approver from recorder and
  bind the source reference. Humans are not expected to run routine CLI gates.

## Invariants

- `passing` and `done` remain distinct states.
- The router does not invent readiness or approval.
- Agent and system actions cannot claim `actor_kind=human`.
- JSON additions are additive and deterministic.
- Existing defect, decision, and escalation priority remains intact unless the
  spec names the exact new comparison.

## Non-scope

- Identity federation or authentication.
- Multi-user permissions.
- Automatic Feature completion.

## Acceptance criteria

1. A passing unfinished Feature produces an actionable non-idle route.
2. Missing required verdicts explain the artifact/policy blocker and safe next
   command.
3. Agent self-review cannot satisfy a human approval requirement.
4. Explicit human approval produces a hash-bound provenance receipt.
5. JSON/text/dashboard ordering and compatibility snapshots are deterministic.
6. Agent-mediated recording of conversational approval preserves separate
   human approver, agent recorder, and source reference fields.
