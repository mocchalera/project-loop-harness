# Direct Setup Bundle v1

`pcl start "<intent>" --direct-spec <path> --json` creates one implementation
setup bundle in an initialized project:

- one open Goal and one linked `in_progress` Task;
- one `needs_test` Feature linked to that Task;
- one or more draft Stories;
- one or more planned Tests linked to those Stories;
- one inline `start-receipt/v1` Evidence record.

It does not approve a Story, register acceptance Evidence, pass a Test, finish
a Feature or Task, or close a Goal. Those remain separate human and
evidence-backed lifecycle operations.

## Input contract

The path is relative to the project root. Absolute paths, `.`, `..`, empty
components, symlinks, non-regular files, and leaves with `st_nlink != 1` are
rejected. Rejecting hardlinks makes project-local provenance unambiguous. The
runtime opens each component relative to a retained root descriptor with
`O_NOFOLLOW`, opens the leaf once, and performs two bounded reads from that
same descriptor with identity checks. The root descriptor and its device/inode
identity remain live through authoritative admission. The mutation connection,
DB target, pre-commit barrier, and projector paths are bound to that same root;
rename or replacement of the requested root fails closed before commit.
Platforms without those capabilities fail closed.

The raw and canonical JSON representations are each limited to 65,536 bytes.
The path is limited to 1,024 UTF-8 bytes and each component to 255 bytes. JSON
is strict: UTF-8 without BOM or unpaired surrogates, no duplicate object keys
at any depth, no trailing content, no `NaN`/infinity, maximum depth 8 with the
root at 1, and maximum 1,024 nodes. Parser limit errors, including Python's
large-integer digit guard, are normalized to typed Direct-spec errors.

```json
{
  "contract_version": "direct-spec/v1",
  "request_id": "ds-20260730-p1a-0001",
  "feature": {
    "name": "Atomic direct setup",
    "surface": "pcl start --direct-spec",
    "description": "Create the lifecycle setup atomically."
  },
  "stories": [
    {
      "ref": "story_atomic",
      "actor": "coding agent",
      "goal": "register setup in one call",
      "benefit": "avoid partial setup",
      "expected_behavior": "The full setup commits or nothing commits."
    }
  ],
  "tests": [
    {
      "ref": "test_atomic",
      "story_ref": "story_atomic",
      "type": "acceptance",
      "scenario": "A valid direct spec is submitted",
      "expected": "All setup entities are created atomically."
    }
  ]
}
```

`request_id` is mandatory, 8–128 UTF-8 bytes, and matches
`[A-Za-z0-9][A-Za-z0-9._:-]*`. Story and Test refs are 1–64 bytes and match
`[A-Za-z][A-Za-z0-9_-]*`. The spec accepts 1–16 Stories and 1–32 Tests. Every
Story must have at least one Test, every `story_ref` must resolve, and at least
one Test must have type `acceptance`. Supported Test types are `unit`,
`integration`, `e2e`, `manual`, `smoke`, and `acceptance`.

Unknown fields and scalar type substitutions are errors. Names and surfaces
are at most 200 UTF-8 bytes, descriptions 2,000, and Story/Test prose 4,000.
All comparisons use the trimmed strings stored by the runtime. The schema file
is [`direct-spec-v1.schema.json`](../src/pcl/contracts/schemas/direct-spec-v1.schema.json);
the runtime additionally enforces byte, resource, duplicate-key, linkage, and
secure-file rules that JSON Schema alone cannot express.

`--dry-run` validates the same spec and reports planned entities without
allocating IDs or changing state. `--new` permits a distinct bundle when active
work exists. `--goal`, `--task`, and `--skill` are incompatible with
`--direct-spec`. Direct Setup never initializes a project implicitly.

## Atomic transaction and events

After a friendly external preflight, Direct Setup acquires the existing
project-operation lock exclusively and starts one `BEGIN IMMEDIATE`
transaction. Schema 8, SQLite integrity, required columns, foreign keys,
relationships, agent lease/concurrency state, event sequence, event/outbox
one-to-one health, pending projection, request identity, and active-work policy
are re-evaluated from that connection with one clock snapshot before ID
allocation.

For `S` Stories and `T` Tests, the transaction appends exactly `6 + S + T`
events and one outbox record for each event:

1. `goal_created`
2. `task_created`
3. `work_started`
4. `feature_added`
5. `task_feature_linked`
6. `user_story_drafted` × `S`
7. `feature_status_updated`
8. `test_case_planned` × `T`

The Feature is inserted as `discovered` and changes to `needs_test` immediately
before the first Test event, matching the existing lifecycle helpers. Every
Story is inserted as `draft`. The response reports human review actions with
`command: null`; spec text is never turned into a shell command.

## Receipt and idempotency

The persisted receipt remains `start-receipt/v1`. Its existing top-level fields
and meanings do not change, and `receipt.created_ids` contains only the new
Goal and Task string IDs. Direct-specific IDs and identity data are additive
under:

```text
receipt.direct_setup / direct-setup-receipt/v1
```

That namespace stores the full normalized request, raw and canonical spec
SHA-256 values, the initial Git revision when available, all bundle/event/
outbox IDs, and the exact event range. A canonical SHA-256 binding covers the
namespace. The `work_started` event and start Evidence store the same receipt.

New request uniqueness is anchored only by the existing `events.id` primary
key:

```text
EV- + all 64 uppercase hex characters of
SHA256("pcl:direct-setup-anchor:v1\0" + request_id UTF-8 bytes)
```

An exact retry verifies the anchor, both stored receipt copies, binding,
request identity, event range, one-to-one delivered outbox records, and domain
state, then returns `status: already_started`, `mutated: false`. Payload scans
are diagnostic only. Collision, ambiguity, corruption, or changed input fails
without creating a fallback bundle.

Bundles created by the initial P1-A implementation may have the former
12-hex/48-bit anchor. That ID is consulted only as a legacy exact-retry
candidate and must pass the complete receipt/identity verification. A valid
legacy anchor for a different request that shares the same 48-bit prefix does
not block the new request's full-SHA-256 anchor.

The initial revision is stored identity. A later current HEAD is returned as a
separate observation and does not invalidate a healthy retry.

## Post-commit tail and recovery

Only a normal service return invokes the Direct mutation tail, at most once per
handler invocation. Each of at most two attempts performs full validation and
exact-target routing while leaving canonical dashboard files unchanged, with
event high-watermark checks after each phase.

A stable validation failure is `partial`: `next_action` is null, routing and
rendering are skipped, artifact hashes are null, and recovery is exactly:

```bash
pcl validate --target T-XXXX --summary --json
```

If validation and routing remain stable and auto-render is enabled, the tail
acquires the existing exclusive project-operation lock, rechecks the
high-watermark, and calls the current canonical renderer at most once while
holding that lock. The lock-held call uses the renderer's non-reentrant
internal path. Standalone CLI, MCP local-render, planning, workflow, and normal
mutation-tail render calls all enter through the same exclusive lock-aware
wrapper. A mismatch retries the complete attempt once; a second mismatch is
partial and does not render. This contract does not claim two-dashboard-file
or process-crash atomic publication.

Renderer failure remains a committed partial result without success artifact
hashes. A pre-existing pending outbox or a projector failure returns exit 6
with no mutation tail:

```bash
pcl audit flush --json
```

Do not edit SQLite, JSONL, or generated dashboard HTML to recover.
