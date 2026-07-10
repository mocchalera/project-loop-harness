# handoff-packet/v1 and `pcl resume`

`pcl resume` builds a small, read-only handoff packet for a Goal or Task. The
JSON packet is the source of truth; Markdown is a human-readable rendering of
the same `verified` and `unverified` arrays.

```bash
pcl resume --json
pcl resume --target T-0001 --format markdown
pcl resume --target G-0001 --format json --output /tmp/handoff.json
pcl contract validate --type handoff-packet/v1 /tmp/handoff.json
```

The command never updates SQLite, appends an event, renders the dashboard, or
starts an agent. `--output` is the only write surface and writes exactly the
selected JSON or Markdown representation.

## Target selection

`--target` accepts a Task (`T-...`) or Goal (`G-...`) ID. Without it, selection
uses this order:

1. the only active Task;
2. the target of the latest valid target-bound completion packet;
3. the only active Goal.

Multiple active Tasks or Goals are not ordered into an implicit winner. The
command exits with `context_pack_target_selection_required` and a deterministic
candidate list. Completed targets remain available through explicit selection,
and the latest completion packet lets the three-command
`start -> finish -> resume` path return to the just-finished Task.

## Claims and references

Only claims already carrying Evidence refs in a valid target-bound
`completion-packet/v1` enter `verified`. Producer-authored unverified claims stay
in `unverified`; generic Evidence summaries and database state are not promoted
to facts.

`context_refs` are selected through `evidence_links`. The newest valid
`completion_packet` link is used and older packets are reported in
`omitted_sections` as superseded. A `code_context` link is accepted as
target-bound only when the receipt artifact's own `target_binding` agrees with
the link target. Repository revision drift and receipt staleness warnings mark
references `stale`; unreadable or unhashed artifacts are `unknown`.

Full transcripts and Evidence bodies are never inlined by default. Every packet
records canonical UTF-8 JSON byte size, `charclass/v1` estimated token count,
and omitted sections. `packet_id` is a SHA-256 content ID over the canonical
packet excluding the ID field itself.

## Contract fields

The authoritative packaged schema is
`pcl/contracts/schemas/handoff-packet-v1.schema.json`. Required fields are:

- identity/provenance: `contract_version`, `packet_id`, `producer`,
  `generated_at`;
- work state: `target`, `current_state`, `summary`;
- trust boundary: `verified`, `unverified`, `decisions`, `blockers`, `risks`;
- continuation: `next_safe_action`, `context_refs`;
- bounds: `token_estimator`, `estimated_token_count`, `size_bytes`,
  `omitted_sections`.

`intent_index_ref` and `budget_remaining` are optional. Markdown wording and
layout are presentation behavior, not a second versioned artifact contract.
