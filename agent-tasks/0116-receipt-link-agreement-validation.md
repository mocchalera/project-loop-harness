# 0116: Target-bound receipt / link agreement validation

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: context/validation
Origin: third-party v0.3.0 post-release review (P1①). Sakamoto approved the
recommended plan 2026-07-09 (integrity pair 0116+0117 first).

## Problem

v0.3.0 selects a target-bound code-context receipt purely from the
`evidence_links` routing row plus the evidence type. `_select_code_context_receipt_ref`
(`context.py:780-791`) reads `newest_linked_evidence_id(... link_role="code_context")`,
loads the evidence row, checks only `evidence_type == context_receipt`, and returns
`"target_bound"`. Downstream, `_latest_code_context_summary` (`context.py:725-751`)
loads the receipt artifact but **never compares the artifact's `target_binding`
to the requested pack target**, and `_code_context_relevance` (`context.py:857`)
stamps `scope: target_bound` from `selection_scope` alone. Strict validation
(`_validate_evidence_links`, `validators.py:621-659`) only checks dangling links
(evidence row exists; `target_id` exists in `tasks`/`agent_jobs`); it does not
read the artifact binding either.

On the normal write path this cannot break: 0108 writes the `evidence_links`
row and the artifact `target_binding` in one transaction with the same target,
and inserts the `code_context` link **only when `target_binding is not None`**
(`code_context/receipts.py:123-129`). But a hand-edited DB, a future writer bug,
a migration accident, or raw SQL can leave the link routing a receipt whose
artifact binding names a *different* target. Today that receipt would surface as
`scope: target_bound` for the wrong target — the exact "target-bound label that
lies" failure this milestone must foreclose.

This is defense-in-depth / corruption resilience, not a normal-path bug. The
guarantee to establish: **nothing is ever reported as `target_bound` unless the
selected receipt artifact's own `target_binding` agrees with the requested
target.**

## Scope

### 1. Agreement predicate (single reusable helper)

Add one pure helper (in `context.py`, or a small shared location `pcl context
check` (0119) can also import — do not duplicate this logic later):

```python
def _receipt_target_binding_agrees(
    receipt_payload: dict[str, Any], *, target_type: str, target_id: str
) -> bool:
    binding = receipt_payload.get("target_binding")
    if not isinstance(binding, dict):
        return False  # a code_context-linked artifact with no binding is anomalous
    return (
        str(binding.get("target_type")) == target_type
        and str(binding.get("target_id")) == target_id
    )
```

Missing / non-dict `target_binding` on a receipt reached through a `code_context`
link counts as **disagreement** (per the 0108 invariant such a link always has a
binding, so its absence is corruption).

### 2. Read-side guard in selection

In `_select_code_context_receipt_ref`, after obtaining the candidate
`receipt_ref` from the link and confirming `evidence_type == context_receipt`,
load the receipt artifact (reuse `resolve_context_receipt_path` +
`json.loads`, both already used at `context.py:725-727`):

- **Artifact load fails** (OSError / JSONDecodeError / not a dict): NOT a
  mismatch. Preserve current behavior — return `(_public_receipt_ref(...),
  "target_bound")` and let `_latest_code_context_summary` render
  `receipt_unavailable`. (Unreadable ≠ disagreement; do not turn transient FS
  errors into mismatches.)
- **Artifact loads and binding agrees**: return `(ref, "target_bound")` (today's
  happy path, unchanged).
- **Artifact loads and binding disagrees** (including missing/blank binding):
  MISMATCH.
  - `require_bound_receipt=True` → raise a new distinct
    `ContextPackBoundReceiptMismatchError` (see §3). Do **not** raise the
    existing `...RequiredError` — the operator must be able to tell "corrupt
    binding" from "no receipt".
  - `require_bound_receipt=False` → skip this receipt and fall through to the
    existing `latest_context_receipt_ref` path, returning `"unscoped_latest"`
    (or `"missing_receipt"` if none). It MUST NOT return `"target_bound"`.
    SHOULD: surface that a mismatched bound link was skipped in the
    `unscoped_latest` relevance `warning` (distinct wording from plain "no
    target-bound receipt found"); if threading a flag is awkward, the MUST
    (never `target_bound`) is sufficient for this task.

### 3. New typed error

Add `ContextPackBoundReceiptMismatchError(PclError)` modeled on
`ContextPackBoundReceiptRequiredError` (`context.py:47-58`):

- `code = "context_pack_bound_receipt_mismatch"`, `exit_code = EXIT_USAGE`.
- `message`: names the target and that a linked receipt's binding disagrees.
- `details`: `target_type`, `target_id`, the offending `evidence_id`, the
  artifact's claimed `target_binding` (as read), and
  `suggested_refresh_commands = [_target_refresh_command(target_type, target_id)]`.

### 4. Strict-validation agreement check

Thread `ProjectPaths` into the evidence-links validation (`validate_project`
already has `paths` at `validators.py:110`; update the call site
`_validate_evidence_links(conn, result)` at `validators.py:266`). For each
`evidence_links` row with `link_role == "code_context"` and a **known**
`target_type`:

- Resolve the receipt artifact via `evidence_ref_by_id(paths, evidence_id)` +
  `resolve_context_receipt_path`.
- If the artifact is **readable** and its `target_binding` disagrees with the
  row's `(target_type, target_id)` (using the §1 predicate), `result.add_error`
  with a message naming the link, the row target, and the artifact's claimed
  binding.
- If the artifact is **missing/unreadable**, add no new error here (existing
  evidence-health / dangling checks own that surface; avoid double-reporting).

Only `code_context` links are checked (supporting links have no artifact
binding). Unknown `target_type` stays tolerated (no error), as in 0113.

## Invariants (what to protect, on the normal paths)

- Normal-path target-bound selection and output are byte-for-byte unchanged: a
  receipt whose artifact binding matches keeps `scope: target_bound` /
  `binding_strength: caller_asserted` and the same `receipt_ref`.
- No new claim vocabulary. Binding stays `caller_asserted`; no
  `verified_relevant` / `safe_to_continue` / `agent_read` / semantic wording.
  A mismatch error states a *fact* ("the routing row and the artifact binding
  disagree"), never a judgment about relevance.
- `pcl` remains the only mutation path; this task adds read-side checks only and
  writes nothing.
- Additive: no schema change (schema stays 7), no migration, no new table or
  column. `require_human_approval: database_migration` does NOT apply.

## Non-scope

- `pcl context check` (0119) — it will import the §1 predicate; do not build the
  command here.
- Auto-repair / re-linking of a mismatched link. Detection and safe refusal
  only; never mutate `evidence_links` to "fix" a mismatch.
- Any change to the 0108 write path (it is already correct and atomic).
- Markdown refresh-command wording (that is 0117).

## Acceptance

- New helper is unit-tested: agrees on matching binding; disagrees on
  mismatched target, on missing `target_binding`, and on non-dict payload.
- Contract fixture added (extend the 0115 code-context contract set): an
  `evidence_links` `code_context` row pointing at target A while the artifact
  `target_binding` names target B —
  - `--require-bound-receipt` → error
    `context_pack_bound_receipt_mismatch` (not `..._required`);
  - default (no require) → `code_context.relevance.scope` is `unscoped_latest`
    or `missing_receipt`, **never** `target_bound`.
- `validate --strict --json` reports the hand-built mismatch row as an error;
  an agreeing `code_context` row and any `supporting` row produce no new error;
  an unknown `target_type` row is still tolerated.
- All existing target-bound / require / unscoped tests stay green (normal path
  unaffected).
- Full `pytest` green; live smoke in a scratch project proving: a normal
  `impact --for-task` + `context pack --require-bound-receipt` still selects
  `target_bound`, and a deliberately corrupted link (built through `pcl`-created
  state, then the `.db` row's `target_id` diverged for the test only) yields the
  mismatch error under `--require-bound-receipt` and `unscoped_latest` without.
