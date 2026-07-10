# Completion Packet v1

`completion-packet/v1` is a stable, read-only artifact contract for reporting a
bounded PLH close-out result across agent and runtime boundaries. It records
claims, checks, repository changes, risks, and the declared outcome without
exposing database rows or making the packet another state store.

The packaged JSON Schema is
`pcl/contracts/schemas/completion-packet-v1.schema.json`. The Python contract
module is `pcl.contracts.completion_packet`. `pcl finish --emit-packet` emits
this artifact through the opt-in execution path documented in `docs/finish.md`;
the default finish planner and the existing `--execute` tail remain unchanged.

## Trust model: claims, not facts

A completion packet is a producer-authored set of claims. PLH validates its
shape, canonical values, and internally checkable consistency. Validation does
not prove that commands were actually run, Evidence content supports a claim,
a diff is complete, a model review is correct, or the outcome is semantically
justified.

This is the same boundary as `master-trace/v0` and `intent-index/v0`: an
Evidence ID proves that PLH recorded an artifact, and a hash identifies bytes.
Neither makes an interpretation true or complete. Consumers must resolve
Evidence refs, inspect the referenced artifacts, and compare claims with the
current task/spec before acting.

Core generation and validation are deterministic and do not call an LLM.
`verifier_provenance.kind: model` records provenance only. A model review alone
never raises proof above L1.

## Canonicalization

- Serialization is UTF-8 JSON with lexicographically sorted object keys, no
  insignificant whitespace, literal Unicode, and no NaN/Infinity values.
- `packet_id` is `cp-sha256:<lowercase hex>`, computed over canonical JSON after
  removing the `packet_id` field. It is content-derived, so changed content
  produces a changed ID without requiring mutable ID allocation or database
  access.
- `generated_at` is an RFC 3339 UTC timestamp at whole-second precision:
  `YYYY-MM-DDTHH:MM:SSZ`. Validation checks that the value is a real calendar
  date, including month lengths and leap years, not only that it matches the
  textual shape.
- `repository.diff_sha256` is `sha256:<64 lowercase hex>` over the exact diff
  bytes selected by the future producer. v1 validates the representation; the
  producer must document/select the bytes and the consumer must reproduce them
  when that distinction matters.
- Array order is producer-significant and is not reordered by the serializer.

## Field semantics

The top-level fields are strict; unknown fields are rejected in v1.

- `contract_version`: exactly `completion-packet/v1`.
- `producer`: PLH name plus the producing runtime version.
- `target`: a `goal` (`G-NNNN`) or `task` (`T-NNNN`), its intent, and an optional
  `evidence:E-NNNN` work-brief ref.
- `repository`: non-empty base/head revisions, canonical diff hash, and an
  explicit dirty flag. Revision strings are identifiers, not proof that the
  referenced commits exist.
- `changes`: paths and change kinds. A renamed entry requires `previous_path`.
- `checks`: distinguish `passed`, `failed`, `skipped`, `not_run`, and
  `timed_out`. `passed` requires exit code 0; non-executed/timeout states require
  a reason. `artifact_ref` is an Evidence ref, not embedded output.
- `claims`: claim-local `critical`, `proof_level`, and Evidence refs.
- `unverified_claims`: explicit unsupported claims with reason and criticality.
- `risks`, `human_decisions`, and `next_action`: remaining close-out context;
  these do not authorize a mutation.
- `verifier_provenance`: optional human/tool/model provenance. It does not
  itself grant a proof level.

Completed outcomes reject critical L0/L1 claims and critical unverified claims.
`COMPLETED_VERIFIED` requires no reported risks;
`COMPLETED_WITH_RISK` requires at least one risk. `NO_CHANGES` requires an empty
change list. `INCOMPLETE_BUDGET_EXHAUSTED` is never treated as completed and
requires a next action.

## Proof levels

`calculate_proof_level()` is a pure, order-independent, fail-closed rule:

| Highest applicable Evidence class | Level | Meaning |
|---|---:|---|
| none or unknown | L0 | unsupported claim |
| `artifact_ref` or `model_review` | L1 | inspectable assertion/review |
| `executed_check` | L2 | a check was recorded as executed |
| `independent_reproduction` | L3 | an independent reproduction was recorded |
| `production_observation` | L4 | production observation was recorded |

The calculator maps caller-supplied classes; it does not verify that the class
is truthful. In particular, adding `model_review` cannot promote L1 to L2.

## Validation CLI and exit codes

```bash
PYTHONPATH=src python -m pcl contract validate \
  --type completion-packet/v1 packet.json
PYTHONPATH=src python -m pcl contract validate \
  --type completion-packet/v1 packet.json --json
```

The command is read-only and does not require an initialized project.

- exit `0`: valid packet;
- exit `1`: readable JSON that violates schema or semantic invariants;
- exit `2`: usage error, unsupported type, unreadable file, or malformed JSON.

Python-style non-standard JSON constants (`NaN`, `Infinity`, and `-Infinity`)
are malformed input and return exit 2. Direct Python validator calls fail
closed with path-addressed errors if a non-finite float is supplied in an
already-decoded payload.

With `--json`, stdout contains exactly one JSON object and diagnostics do not
leak to stderr. Without `--json`, success goes to stdout and validation errors
go to stderr.

## Versioning and compatibility

Within v1, new producers must preserve required fields and their meanings.
Because v1 uses `additionalProperties: false`, adding a field is a contract
change that requires schema, validator, fixture, and documentation updates;
consumers should not silently discard fields. A removal, rename, type change,
meaning change, relaxed/tightened identity rule, or changed proof/outcome rule
requires `completion-packet/v2` unless a reviewed v1 clarification proves it
does not invalidate conforming packets.

The planning bundle schema was the starting proposal. The implemented v1
differs by using PLH `G-NNNN` / `T-NNNN` target IDs and `evidence:E-NNNN` refs,
requiring explicit null/default-bearing fields for deterministic interchange,
defining `verifier_provenance`, enforcing canonical timestamp/diff/packet IDs,
and adding semantic outcome/check/claim rules. The repository task spec,
packaged schema, validator, fixtures, and this document are authoritative.

## Non-guarantees

Validation does not guarantee command execution, artifact availability,
Evidence relevance, test coverage, repository cleanliness, diff completeness,
review independence, production safety, approval, or readiness to deploy. The
packet is not a database snapshot, dashboard input, remote-upload protocol,
handoff packet, or authorization to run `next_action.command`.
