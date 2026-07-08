# 0115: Context pack target-bound contract fixtures

Milestone: v0.3.0 Target-Bound Context
Priority: P2
Area: context-pack/tests
Origin: docs/growth-plan-v0.2.4-v0.5.md v0.3.0; third-party review 0111 —
required in v0.3.0 (坂本承認 2026-07-08). Depends on 0108 and 0113.

## Problem

0108 changes the `context-pack/v1` code-context contract: `code_context.relevance`
gains `scope: "target_bound"` / `binding_strength: "caller_asserted"` with
`target_type` / `target_id`, a `receipt_ref`, a `--require-bound-receipt` typed
error, and target-specific `suggested_refresh_commands`. PLH has shipped three
contract regressions caught only in review (0087 git-status key loss, 0089
audit-mirror break, 0090 receipt-content storage). Freeze the v0.3.0 handoff
contract with deterministic fixture-based tests so future changes are provably
additive and any silent shape change fails a test.

## Scope

Add fixture-backed tests covering six code-context selection states. Each
fixture asserts `included_sections`, the required / non-droppable safety
sections, `source_paths`, `suggested_refresh_commands`, and
`code_context.relevance`:

1. **no receipt** — `scope: "missing_receipt"`, `binding_strength: "none"`.
2. **unscoped latest only** — a receipt with no `target_binding`;
   `scope: "unscoped_latest"`, `binding_strength: "none"`, with the existing
   unscoped warning and a target-specific suggested refresh command.
3. **matching task-bound receipt** — `scope: "target_bound"`,
   `binding_strength: "caller_asserted"`, `target_type: "task"`, `target_id`
   set; chosen over a newer unbound receipt.
4. **matching job-bound receipt** — same as (3) with `target_type: "agent_job"`.
5. **stale bound receipt** — a matching bound receipt old enough that the 0082
   `age_warning` fires; relevance stays `target_bound` and the age warning is
   present (staleness is a surfaced fact, not a downgrade).
6. **require-bound missing** — `--require-bound-receipt` with no matching bound
   receipt → typed error `context_pack_bound_receipt_required` with the
   target-specific refresh suggestion; assert there is **no** silent fallback to
   unscoped latest.

## Invariants (what to protect, on the normal paths)

- Fixtures are byte-deterministic: inject `now` at the CLI boundary the way
  existing pack tests do; no wall-clock reads inside generated artifacts.
- Budget truncation never drops required safety sections: the
  `code_context_safety` pin (priority 10000, 0078/0083) survives a deliberately
  tight budget — at least one fixture asserts this.
- Contract assertions are additive-only in spirit: adding a new field is
  allowed; changing or removing an asserted field, shape, or ordering must fail
  a fixture. Do not weaken an assertion to make a change pass.
- Fixtures must not inline receipt bodies or copied evidence file contents
  (0090 boundary): assert `receipt_ref` carries `evidence_id` / `receipt_path`
  only.

## Non-scope

- Any new runtime behavior — this is a pure test / fixture task. If a fixture
  reveals a 0108 defect, fix it in 0108, not here.
- Dashboard, MCP, or CLI-surface changes.
- Golden-file snapshotting of the entire pack (assert the contract-bearing
  fields, not incidental whitespace).

## Acceptance

- Six fixtures committed and green.
- A deliberate contract break (e.g., dropping `binding_strength` from
  `relevance`, or letting `--require-bound-receipt` fall back silently) makes at
  least one fixture fail with a clear message.
- The tight-budget fixture proves the safety section is never truncated away.
- Full `pytest` green.
