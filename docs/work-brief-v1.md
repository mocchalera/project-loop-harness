# Work Brief v1

`work-brief/v1` is an immutable, target-bound execution-input artifact. It
captures intent, acceptance criteria, constraints, non-goals, and assumptions
without creating a first-class Intent table or embedding a route decision.

## Contract boundary

- The artifact is Evidence, not fact. Assumptions retain their explicit status.
- Route recommendation is a separate artifact; it is not required to create a
  valid Work Brief.
- Approval does not rewrite the JSON. `pcl brief approve` appends an event bound
  to the Evidence ID, target, and current artifact SHA-256.
- `pcl brief review` records hash-bound human, agent, or system review
  provenance without satisfying approval. Only `actor_kind=human` may approve.
- A target may have only one current approved brief. A conflicting second
  approval fails closed.
- DB schema remains 8.

Validate a file without initializing or mutating a project:

```bash
pcl contract validate --type work-brief/v1 work-brief.json --json
```

Preview and record immutable Evidence:

```bash
pcl brief add work-brief.json --summary "Reviewed execution input" --dry-run --json
pcl brief add work-brief.json --summary "Reviewed execution input" --json
```

Inspect by Evidence or target:

```bash
pcl brief show --evidence E-0001 --json
pcl brief show --target task:T-0001 --json
```

An agent or system may record a review without closing the human gate:

```bash
pcl brief review E-0001 \
  --actor "agent:codex" \
  --actor-kind agent \
  --reason "Self-review completed; request human approval" \
  --json
```

The normal approval UX is conversational: the agent presents a review packet,
the human replies approve/reject/hold, and the agent records that explicit
decision. The human does not need to run `pcl`:

```bash
pcl brief approve E-0001 \
  --actor "human:owner" \
  --actor-kind human \
  --recorded-by "agent:codex" \
  --recorder-kind agent \
  --source-kind conversation \
  --source-ref "conversation:<approval-reference>" \
  --reason "Human explicitly approved the presented review packet" \
  --json
```

Agent/system-mediated approval is rejected unless it carries a conversation
or Cockpit source reference. A human may still run the shorter direct CLI form
for compatibility; in that case approver and recorder are the same human and
the source is `pcl brief approve`.

Every receipt exposes `actor_kind`, approver identity, recorder kind/identity,
source kind/reference, timestamp, target, Evidence ID, and artifact SHA-256.
Task context packs and handoff
packets include only the approved brief's reference, hash, summary, and
approval provenance. Dashboard data lists recent approval/review provenance.
These views do not inline the full brief or promote its assumptions into
verified facts.

## Supported targets

`goal`, `task`, `feature`, `story`, `defect`, and `workflow_run` are accepted
when the referenced entity already exists. Unknown targets are rejected before
Evidence, files, events, or outbox records are created.

## Compatibility

Projects with no Work Brief retain the existing `start -> finish -> resume`
behavior. Schema-6 context fallback also continues to work without an
`evidence_links` table. The packaged JSON schema is available through
`pcl.contracts.work_brief.work_brief_schema()`.
