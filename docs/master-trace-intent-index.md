# Master Trace / Intent Index v0

This document defines the v0 evidence contracts for pull-based handoff from a
master trace to a worker. The contracts formalize the shape proven by the
[historical M0 dogfood runbook](master-trace-handoff.md); they do not add a new
entity, schema migration, or CLI command.

Project Loop Harness (PLH) records and routes these artifacts as evidence. An
external agent may create an intent index, but `pcl` core does not call an LLM
or determine whether an index is correct, complete, or semantically sufficient.

## Contract boundaries

- `master-trace/v0` is a line-addressable transcript or trace artifact recorded
  with copied evidence.
- `intent-index/v0` is model output containing claims that point into one
  copied master trace. Its items are navigation pointers, not verified facts.
- `master-trace-context/v0` is an opt-in context-pack section. It
  carries evidence and path references only; it never carries raw transcript
  contents.
- SQLite state and append-only JSONL events remain authoritative for evidence
  records and links. The artifacts are evidence, not another state store.
- The current `context-pack/v1` `linked_evidence` behavior is unchanged.

## `master-trace/v0`

A master trace is UTF-8 text whose physical lines can be addressed after it is
copied. Markdown is recommended because it stays inspectable without a custom
reader. The payload identifies its contract in front matter:

```markdown
---
contract_version: master-trace/v0
trace_id: mt-2026-07-10-001
source_kind: agent_transcript
captured_at: 2026-07-10T09:30:00Z
---
# Session trace

The operator requested a docs-only contract slice.
The worker must not add a schema migration or a new command.
```

The following rules define a valid v0 trace:

1. `contract_version` is exactly `master-trace/v0`.
2. `trace_id` identifies this captured artifact; it is not a PLH entity ID.
3. `source_kind` describes the external source, for example
   `agent_transcript`, `meeting_transcript`, or `operator_notes`.
4. `captured_at` is an RFC 3339 timestamp supplied by the producer.
5. Line references are one-based and inclusive over the complete copied UTF-8
   file, including front matter and blank lines.
6. After an intent index is generated, the copied trace is immutable for that
   index. A changed trace is captured as new evidence and receives a new index.

The evidence record and its `adhoc-evidence/v0` manifest supply the durable
identity around the payload: evidence ID, manifest path, original member path,
copied `stored_path`, size, and SHA-256. Consumers use the copied `stored_path`
when checking line references. The original member path is provenance and may
later disappear or drift.

## `intent-index/v0`

An intent index is JSON produced outside `pcl`. It identifies the copied trace
it indexed and provides source references for every claim:

```json
{
  "contract_version": "intent-index/v0",
  "index_id": "ii-2026-07-10-001",
  "generated_at": "2026-07-10T09:35:00Z",
  "generator": "external-indexing-agent",
  "source_trace": {
    "evidence_id": "E-0042",
    "manifest_path": ".project-loop/evidence/adhoc/e-0042-adhoc-v0.json",
    "member_path": ".work/master-trace-2026-07-10.md",
    "stored_path": ".project-loop/evidence/adhoc-files/e-0042/01-master-trace-2026-07-10.md",
    "sha256": "d2ef320a7da51347036ed5ef4d47c4b098c30adf2097b6634ffdf687a64fa70c"
  },
  "items": [
    {
      "id": "I-001",
      "kind": "task_hint",
      "claim": "The requested slice is documentation-only.",
      "source_refs": [
        {
          "evidence_id": "E-0042",
          "stored_path": ".project-loop/evidence/adhoc-files/e-0042/01-master-trace-2026-07-10.md",
          "line_start": 9,
          "line_end": 10
        }
      ]
    }
  ]
}
```

The following rules define a valid v0 index:

1. `contract_version` is exactly `intent-index/v0`.
2. `index_id`, `generated_at`, and `generator` identify the external indexing
   run. PLH stores these caller-provided values without validating the model.
3. `source_trace` identifies one copied `master-trace/v0` evidence member. Its
   `evidence_id`, paths, and SHA-256 must match that copied evidence manifest.
4. `items` is an array. Every item has an index-local `id`, a descriptive
   `kind`, a model-derived `claim`, and one or more `source_refs`.
5. Each source ref names the same trace evidence and copied `stored_path` as
   `source_trace`. `line_start` and `line_end` are positive, one-based,
   inclusive integers with `line_start <= line_end`.
6. An item without a source ref is not a valid v0 index item.

Kinds are descriptive and open-ended in v0. Examples include `task_hint`,
`constraint_hint`, `decision_hint`, and `open_question`. A kind does not confer
verification status or execution authority.

## Trust model and worker discipline

The intent index is model output. Its claims can omit context, misstate the
trace, point at the wrong lines, or preserve an idea that the trace later
rejects. PLH records the artifact and its task link; that linkage is also a
caller assertion, not semantic verification.

Before acting on an index item, a worker must:

1. Open the copied intent-index member from its evidence `stored_path`.
2. Resolve each actionable item's `source_refs` to the copied master-trace
   `stored_path`, not merely the original working path.
3. Compare the claim with the complete referenced line range.
4. Read enough surrounding copied lines to identify qualifications, rejection,
   supersession, or scope boundaries.
5. Act only on the meaning supported by those copied lines and the current
   task contract. If they conflict or do not support an action, report the
   mismatch rather than treating the index item as fact.

An evidence ID proves that PLH recorded an artifact. A copied-file hash proves
which bytes were recorded. Neither proves that an index interpretation is
correct or complete.

## Current command sequence

The recommended current flow assumes the target task already exists. It uses
only existing CLI surfaces and requires no direct database access or generated
dashboard parsing.

First, capture the `master-trace/v0` file as copied evidence linked to the task:

```bash
PYTHONPATH=src python -m pcl evidence add \
  --file .work/master-trace-2026-07-10.md \
  --summary "Master trace for T-0042" \
  --command "external master session transcript" \
  --task T-0042 \
  --copy \
  --json
```

Use the returned evidence ID, manifest path, member path, copied `stored_path`,
and SHA-256 to build `intent-index/v0` outside PLH. Do not edit the copied trace
after indexing. Then record the index as a second copied evidence item linked
to the same task:

```bash
PYTHONPATH=src python -m pcl evidence add \
  --file .work/intent-index-2026-07-10.json \
  --summary "Model-derived intent index for T-0042" \
  --command "external indexing agent over copied master trace E-0042" \
  --task T-0042 \
  --copy \
  --json
```

Run the read-only preflight and build the opt-in task context pack:

```bash
PYTHONPATH=src python -m pcl context check --task T-0042 --json
PYTHONPATH=src python -m pcl context pack \
  --task T-0042 \
  --master-trace-context \
  --json
```

The task pack exposes linked-evidence metadata and paths. With the opt-in flag,
it also emits `master_trace_context` after resolving the trace and index from
supporting `evidence_links`. The worker opens the copied members and applies the
source-ref checks above. The pack does not inline either artifact. Without the
flag, context-pack output remains unchanged.

If a task has not been selected yet, the base form is still available:

```bash
PYTHONPATH=src python -m pcl evidence add \
  --file .work/master-trace-2026-07-10.md \
  --summary "Unassigned master trace" \
  --copy \
  --json
```

That command records copied evidence but does not put it in a task pack.
Current PLH has no arbitrary retroactive evidence-link command, so new handoff
runs should select the task first and use `--task T-XXXX --copy` for both
artifacts.

`pcl context check` also reports code-context receipt state when applicable.
Master-trace source-ref verification remains the worker's responsibility; the
preflight does not validate the index's meaning.

## Optional `master-trace-context/v0`

The payload below is emitted as an optional `context-pack/v1` section when
`pcl context pack --task T-XXXX --master-trace-context` resolves exactly one
linked `master-trace/v0` evidence item and exactly one linked
`intent-index/v0` evidence item whose copied member paths resolve.

```json
{
  "contract_version": "master-trace-context/v0",
  "target": {
    "type": "task",
    "id": "T-0042"
  },
  "master_trace": {
    "evidence_id": "E-0042",
    "manifest_path": ".project-loop/evidence/adhoc/e-0042-adhoc-v0.json",
    "member_paths": [
      ".work/master-trace-2026-07-10.md"
    ],
    "stored_paths": [
      ".project-loop/evidence/adhoc-files/e-0042/01-master-trace-2026-07-10.md"
    ]
  },
  "intent_index": {
    "evidence_id": "E-0043",
    "manifest_path": ".project-loop/evidence/adhoc/e-0043-adhoc-v0.json",
    "member_paths": [
      ".work/intent-index-2026-07-10.json"
    ],
    "stored_paths": [
      ".project-loop/evidence/adhoc-files/e-0043/01-intent-index-2026-07-10.json"
    ]
  },
  "trust_model": "claims-not-facts",
  "source_ref_discipline": {
    "line_numbering": "one-based-inclusive",
    "read_target": "copied-master-trace-stored-path",
    "worker_must_compare_claim_to_trace_lines": true
  },
  "raw_transcript_inlined": false
}
```

The implementation preserves the following boundaries:

- emit evidence IDs, manifest paths, member paths, and copied `stored_paths`;
- do not inline raw trace or index contents in context packs or dashboard data;
- do not replace or reinterpret existing `linked_evidence` behavior;
- do not claim that an external model's output has been semantically validated;
- keep context-pack generation read-only.

The opt-in section reports `status: "absent"` with `missing` kinds when linked
trace or index evidence cannot be found. If more than one candidate exists for
either kind, it reports `status: "selection_required"`, the ambiguous kinds,
and candidate evidence/path references instead of choosing by recency. If a
single candidate pair exists but a copied member path cannot be resolved, it
reports `status: "unavailable"` and the unresolved member references.

`pcl context check --task T-XXXX` reports the same factual preflight under
`master_trace_context`. The preflight reads evidence rows, manifests, and local
artifact contract markers; it does not score or interpret intent-index claims.

## Future promotion gates

These promotions are outside v0.3.2 and require separate work:

1. First-class `pcl intent` or `pcl collect` surfaces require a separate design
   and human approval because they introduce product semantics and may require
   a schema migration.
2. `pcl option` must be designed against the existing decision lifecycle, and
   `pcl replan` must account for `pcl next` ordering. Both belong to later
   roadmap phases and require human approval before implementation.
3. A knowledge ledger is also deferred. Any later design must keep durable
   state in the PLH control plane and treat Markdown as an export or review
   surface; it requires separate human approval.

No `pcl intent`, `pcl collect`, `pcl option`, `pcl replan`, or knowledge-ledger
command is introduced by this contract.
