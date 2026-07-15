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

Generated packets include the optional additive `restart_context` object. It
keeps the target intent factual, labels acceptance as `intent_only` when no
work-brief Evidence ref was recorded, and labels it `work_brief_linked` only
when the selected completion packet actually carries that ref. Existing valid
v1 packets without `restart_context` remain valid.

`verification_commands` are deduplicated reproducible commands copied from the
selected completion packet's `checks`, together with their previous status,
check Evidence refs, and proof-source check ID. They are replay instructions:
`pcl resume` does not rerun them and does not turn their previous status into a
new verification fact. For duplicate commands, the latest numeric CHK ordering
is authoritative for status and proof source; Evidence refs from all occurrences
are retained in CHK order. No command is inferred from package scripts. For a
terminal target, the first deterministically ordered authoritative passed check
becomes `next_safe_action.command`, unless an open human decision or explicit
completion-packet `next_action` takes precedence. A command whose latest check
failed is never recommended.

`evidence_resolution_commands` contains one public metadata lookup per
referenced Evidence ID. `changed_paths` and `documentation_candidates` are
sorted, deduplicated navigation hints capped at 50 paths. A README,
CONTRIBUTING file, or file under `docs/` is only a documentation candidate; the
packet does not claim that it is authoritative. The restart context never
infers a launch URL or acceptance criteria.

## Evidence metadata lookup

```bash
pcl evidence show E-0001
pcl evidence show E-0001 --json
```

`pcl evidence show` is read-only. It returns the Evidence ID, type, summary,
caller-claimed command, recorded path, and creation time. For supported
`adhoc-evidence/v0` manifests it also returns member paths, copied stored paths,
and recorded hashes. It does not inline member bytes, completion-check output,
or transcripts, and it never executes the claimed command.

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

`intent_index_ref`, `budget_remaining`, and `restart_context` are optional.
Markdown wording and layout are presentation behavior, not a second versioned
artifact contract.

## Frozen Trace extension boundary

Task 0180 implements `trace_claim_refs` as an optional additive field for
bounded `intent-index/v0` items after Task 0179 source-binding validation. The
fixture contract is
`tests/fixtures/trace_binding_v0/trace-binding-fixtures.json`.

Every entry remains model-derived and explicitly `unverified`. A source-bound
claim is not a member of `verified`, and source
binding alone is not semantic verification. Entries carry line coordinates and
copied artifact references, never raw trace or resolved source-line text.
`trace_claim_ref_budget` freezes the 8-item/4096-byte complete-item cap, while
`trace_claim_ref_omissions` records excluded item IDs and reasons. All three
fields appear together only for a valid binding. Packets that omit them remain
valid v1 packets.
