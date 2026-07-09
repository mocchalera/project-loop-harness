# 0119: `pcl context check` — read-only target-bound handoff preflight

Milestone: v0.3.1 Handoff Integrity + Operator Experience
Priority: P1
Area: cli/context
Origin: third-party v0.2.4 + v0.3.0 reviews (context-check deferred to v0.3.1);
Sakamoto approved starting 0118+0119 together 2026-07-09. Builds on 0116.

## Problem

Today an operator or agent only learns whether a target has a usable
target-bound code-context receipt by *running* `pcl context pack
--include-code-context --require-bound-receipt` and reading the error, or by
inspecting `relevance.scope` in a full pack. There is no cheap, read-only
preflight that answers, for a task or job: is there a target-bound code-context
receipt, is it the corrupt (mismatched) kind, how much supporting evidence is
linked, and what is the exact canonical command to produce a bound handoff.

Add `pcl context check`: a **read-only** diagnostic that reports these facts and
the next command, without mutating anything and without running `index build` or
`impact`.

## Scope

### CLI
Add a sibling of `context pack` under the existing `context` subparser
(`cli.py:587-589`):

```
pcl context check (--task T-XXXX | --job J-XXXX) [--json] [--require-bound-receipt]
```

- `--task` / `--job` are a required mutually-exclusive group (mirror
  `context pack`, `cli.py:590-592`).
- `--require-bound-receipt`: optional; changes exit behavior (see Exit codes).
- Dispatch under `if args.command == "context" and args.context_command ==
  "check":` next to the `pack` handler (`cli.py:1923`). Emit
  `_print_json({"ok": True, "context_check": payload})` for `--json`, else a
  short factual text summary.

### Behavior (read-only)
Implement a `context_check_for_task` / `context_check_for_job` (or one
`check_context(paths, *, target_type, target_id, ...)`) in `context.py` that:

1. Validates the target id shape and existence by reusing the impact validators
   `_validate_target_id_shape` + `_require_existing_target`
   (`code_context/impact.py`) so a bad/absent target raises the same typed
   `ImpactTargetError` (`impact_target_invalid` / not-found) as `impact
   --for-task`. Do not invent a new not-found error.
2. Determines the target-bound code-context status by reusing 0116 machinery,
   read-only:
   - `newest_linked_evidence_id(conn, target_type, target_id,
     link_role="code_context")`;
   - if found and the evidence row is a `context_receipt`, load the artifact and
     apply `_receipt_target_binding_agrees` (from `context_binding.py`):
     agree -> `status: "present"`; disagree/missing-binding -> `status:
     "mismatched"`; artifact unreadable -> `status: "present"` is NOT claimed —
     report `status: "unavailable"` (cannot confirm agreement) rather than
     asserting a bound receipt;
   - if no `code_context` link -> `status: "missing"`.
3. Counts supporting evidence: number of `evidence_links` rows for
   `(target_type, target_id, link_role="supporting")` (a `SELECT COUNT` read;
   the existing supporting-link query is at `context.py:1419`). SELECT-only reads
   are allowed; this task writes nothing.

### Output payload (`context_check`)
Factual fields only:
- `target`: `{ "type": "task"|"agent_job", "id": "T-XXXX" }`
- `supporting_evidence_count`: int
- `target_bound_code_context`: `{ "status": "present"|"missing"|"mismatched"|
  "unavailable", "receipt_ref"?: {"evidence_id","created_at"},
  "claimed_target_binding"?: <on mismatched> }`
- `canonical_context_pack_command`: the exact command a caller should run for a
  strict bound handoff, e.g.
  `pcl context pack --task T-XXXX --include-code-context --require-bound-receipt
  --json` (job variant with `--job`).
- `recommended_refresh_command`: `_target_refresh_command(target_type,
  target_id)` — present when status is `missing`/`mismatched`/`unavailable`.
- `warnings`: list of factual strings (e.g. `"No target-bound code context
  receipt exists for this task."`, `"A code_context link disagrees with its
  artifact binding."`).

### Exit codes
- Default (no `--require-bound-receipt`): the diagnostic itself succeeded ->
  exit 0, status in payload, even when `status != present`.
- Bad/absent target: typed `ImpactTargetError` -> exit 2 (existing behavior).
- With `--require-bound-receipt`: exit 2 when `status != present`, raising the
  SAME typed errors as `context pack` for scriptable parity —
  `context_pack_bound_receipt_required` for `missing`/`unavailable`,
  `context_pack_bound_receipt_mismatch` for `mismatched`. (Reuse the existing
  error classes from `context.py`.)

## Invariants (what to protect)

- **Read-only.** `context check` MUST NOT run `index build`, MUST NOT run
  `impact`, and MUST NOT write any evidence row, event, `evidence_links` row, or
  artifact. It only does SELECT reads and reads a receipt artifact file. A test
  MUST assert row/event/adhoc-file counts are identical before and after.
- **Epistemic discipline (hard).** Report facts about *what exists*, never a
  sufficiency/safety/relevance judgment. Do NOT add `ready_for_handoff`,
  `safe_to_continue`, `safe_to_run`, `verified_relevant`, `agent_read`,
  `semantic_match`, or any go/no-go or cognition field — **even though the
  originating third-party review sketched `ready_for_handoff`, we deliberately do
  not adopt it.** `binding_strength` stays `caller_asserted` where surfaced. A
  test MUST assert these forbidden keys are absent from the JSON.
- Additive: no schema change, no migration, no new table/column. No change to
  `context pack` behavior or output.
- `pcl` stays the only mutation interface; this command mutates nothing.

## Non-scope

- README / adoption-guide / `docs/context-pack.md` / `docs/code-context.md`
  edits — those belong to **0118** (disjoint ownership; do not touch them). If a
  command-surface contract test or doc must be updated to register the new
  subcommand and it is one of those four files, STOP and report the conflict
  instead of editing it.
- `pcl context prepare` / pre-work context synthesis (v0.4).
- Any staleness scoring beyond echoing the receipt `created_at` (no new age
  policy; you may include an age in seconds computed from an injected `now`, but
  it is optional).
- Auto-running refresh or repairing a mismatch.

## Acceptance

- `pcl context check --task T-XXXX --json` on a task with a matching bound
  receipt -> `status: present`, `receipt_ref` populated, `supporting_evidence_count`
  correct, `canonical_context_pack_command` present, exit 0.
- Missing bound receipt -> `status: missing`, `recommended_refresh_command`
  target-specific, exit 0; with `--require-bound-receipt` -> exit 2 and
  `context_pack_bound_receipt_required`.
- Mismatched link (as built by the 0116 contract fixture pattern) -> `status:
  mismatched`, exit 0; with `--require-bound-receipt` -> exit 2 and
  `context_pack_bound_receipt_mismatch`.
- Job variant works symmetrically.
- Bad/absent target id -> typed error, exit 2.
- Read-only proof test: evidence/event/adhoc-file counts unchanged across a
  `context check` invocation.
- Forbidden-key test: `ready_for_handoff` / `safe_*` / `verified_relevant` /
  `agent_read` / `semantic_match` absent from the payload.
- New `docs/context-check.md` documents the command (read-only, the four status
  values, the canonical command, exit-code behavior).
- `ruff` clean; full `pytest` green (v0.3.1 baseline 488; expect > 488).
- Live smoke (`python -m pcl` in a fresh scratch repo): build a bound receipt,
  `context check` -> present; a second task with none -> missing (+ exit 2 under
  `--require-bound-receipt`); paste the JSON for both.
