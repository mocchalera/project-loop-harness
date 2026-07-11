# 0146: Immutable Work Brief Evidence contract

- **Status:** Done; human-approved 2026-07-11
- **Milestone:** v0.4.2 Adaptive Entry
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** v0.4.1 released; schema 8 consistent
- **Parallel-safe with:** none
- **DB schema:** remains 8

## Problem

Goal and Task state do not carry a compact, versioned execution input covering
problem, outcome, acceptance criteria, constraints, non-goals, and assumptions.
The integrated proposal embeds route output in the brief and stores mutable
approval status inside an otherwise immutable artifact, creating a dependency
cycle and unclear authority.

## Goal

Package `work-brief/v1` as immutable Evidence content. Link it to an existing
target through generic Evidence links and record approval as a separate,
hash-bound mutation event.

## Contract

- Required content: contract version, brief ID/revision, target, intent,
  acceptance criteria, constraints, non-goals, assumptions, created-at/by.
- Route is not required or embedded. A later optional
  `route_recommendation_evidence_id` may reference 0147 output.
- Artifact content never changes in place.
- `pcl brief approve` records actor, reason, Evidence ID, target, and artifact
  SHA-256 through the normal event/outbox transaction.
- The authoritative current brief is the uniquely approved, non-revoked brief
  for the target. Ambiguity fails closed.

## Scope

- Package JSON schema, validator, positive/negative fixtures, and CLI contract
  validation.
- Add read-only `pcl brief show` / target resolution.
- Add explicit `pcl brief add` and `pcl brief approve` mutations reusing
  Evidence storage/link services.
- Add optional brief reference/summary to context pack and handoff packet.
- Keep bare `pcl start` unchanged; any brief creation integration is explicit.

## Invariants

- No dedicated brief/intent table or migration.
- Unapproved brief is never the critical execution contract.
- Approval does not prove assumptions or Evidence claims.
- Invalid schema, target mismatch, hash drift, or ambiguous approvals fail
  before state/event/file mutation.
- Read-only commands do not record usage or write artifacts by default.

## Acceptance criteria

- Valid brief can be copied as Evidence and target-linked.
- Invalid brief creates no DB row, event, outbox record, or final artifact.
- Approval is auditable and bound to the exact artifact hash.
- Multiple active approvals fail with a typed ambiguity error.
- Context/resume show the approved brief reference without inlining the full
  body.
- Projects without a brief retain byte-compatible default start/finish/resume
  behavior.
- Schema is present in wheel and sdist.

## Required tests

Schema fixtures; add/link/approve/show; hash/target/ambiguity negatives;
read-only zero-mutation checks; packet/context compatibility; package-data and
clean-wheel smoke.

## Non-goals

Route resolution, policy axes, revision/supersession workflow, LLM authoring,
Markdown/YAML authoring, Option generation, or Knowledge.
