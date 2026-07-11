# Approval provenance v1

`approval-provenance/v1` is an additive event receipt for a review or approval
of immutable Evidence. It is stored in the existing event log; DB schema stays
at 8.

```json
{
  "contract_version": "approval-provenance/v1",
  "action": "approval",
  "actor_kind": "human",
  "actor": "human:owner",
  "recorder_kind": "agent",
  "recorder": "agent:codex",
  "source": "conversation",
  "source_kind": "conversation",
  "source_ref": "conversation:current-thread-explicit-approval",
  "timestamp": "2026-07-11T00:00:00+00:00",
  "target": {"type": "task", "id": "T-0001"},
  "bound_evidence": {
    "id": "E-0001",
    "artifact_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  },
  "reason": "Acceptance contract reviewed"
}
```

`actor_kind` describes the approver/reviewer. `recorder_kind` describes who
actually executed the PCL mutation. Both are restricted to `human`, `agent`,
or `system` and must agree with namespaced identities when supplied. An agent
may record a human approval only with `source_kind=conversation` or `cockpit`
and a non-empty `source_ref`. Review receipts may use any actor kind. Agent
self-review is recorded with `pcl brief review` and leaves the human approval
gate unresolved.

Receipts are visible through `pcl brief show`, task context packs, resume
handoffs, and `.project-loop/dashboard/dashboard-data.json`. They state who or
what made the recorded claim and which bytes were reviewed. They do not
authenticate identity, scrape conversation contents, or turn the underlying
Work Brief claims into facts. They preserve the factual distinction between
the human decision and the agent that recorded it.
