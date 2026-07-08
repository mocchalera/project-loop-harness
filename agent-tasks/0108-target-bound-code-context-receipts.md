# 0108: Target-bound code context receipts

Milestone: v0.3.0 Target-Bound Context
Priority: P1
Area: code-context/context-pack
Origin: docs/growth-plan-v0.2.4-v0.5.md v0.3.0; docs/project-loop-harness-v0.2.3-third-party-review.md P2-3
Depends on: 0113 (evidence_links table, migration 007) — merge first.

> **Revision 2026-07-08 (坂本承認):** the original no-migration invariant is
> **retracted**. Target binding is now persisted as a queryable `evidence_links`
> row (`link_role="code_context"`, from 0113) **and** embedded in the receipt
> artifact; receipt selection is a SQL query, not an artifact scan. This unblocks
> `pcl context check` (v0.3.1) and v0.4 `bound_receipt_coverage` without a second
> migration later.

## Problem

`pcl context pack --include-code-context` currently reads the latest
`context_receipt` evidence row. The pack tells the reader that this is
`scope: "unscoped_latest"` with `binding_strength: "none"`, which is honest,
but it still risks handing a worker a receipt from an unrelated task or job.

The existing docs reserve `scope: "target_bound"` and
`binding_strength: "caller_asserted"`, but there is no command path that
creates or requires such a receipt. v0.3.0 turns that reserved contract into a
narrow, explicit handoff workflow, backed by queryable link state.

## Scope

1. Extend `pcl impact --diff` with explicit target flags:
   - `--for-task T-XXXX`
   - `--for-job J-XXXX`
   Exactly zero or one target flag is allowed. Existing diff mode flags
   (`--base`, `--staged`, `--unstaged`, `--include-untracked`,
   `--all-changes`, and provided diff input) keep their current semantics.
2. Validate the named target before writing a receipt. Missing or malformed
   target IDs must fail with a typed error and must not create evidence or an
   `evidence_links` row.
3. When a target flag is present, record the binding in **two** places, in the
   same transaction that writes the receipt evidence:
   - An `evidence_links` row (0113 helper): `(evidence_id=<receipt>,
     target_type, target_id, link_role="code_context", created_at)`, where
     `target_type` is `task` or `agent_job`.
   - Target binding metadata inside the `impact/v0` response and the
     `context-receipt/v0` artifact so the receipt is self-describing:
     ```json
     {
       "target_binding": {
         "target_type": "task",
         "target_id": "T-0001",
         "binding_strength": "caller_asserted",
         "source": "impact_flag"
       }
     }
     ```
     For job targets, use `target_type: "agent_job"`. The link row and the
     artifact `target_binding` must agree.
4. Update context-pack receipt selection when `--include-code-context` is used.
   Selection is a **query on `evidence_links`** (0113 helper), not an artifact
   scan:
   - For a task pack, prefer the newest receipt evidence with a matching
     `evidence_links` row `(target_type="task", target_id=<task>,
     link_role="code_context")`.
   - For a job pack, prefer the newest matching
     `(target_type="agent_job", target_id=<job>, link_role="code_context")`.
   - If no matching bound receipt exists, preserve the current unscoped latest
     fallback unless the caller requires a bound receipt.
5. Add `pcl context pack --require-bound-receipt`, valid only with
   `--include-code-context`. When no matching bound receipt exists, fail with a
   typed error `context_pack_bound_receipt_required` and include a
   target-specific refresh suggestion:
   - `pcl impact --diff --for-task T-XXXX --json`
   - `pcl impact --diff --for-job J-XXXX --json`
6. Update `code_context.relevance` in the embedded summary:
   - Matching bound receipt: `scope: "target_bound"`,
     `binding_strength: "caller_asserted"`, plus `target_type` and
     `target_id`.
   - Unbound fallback: keep `scope: "unscoped_latest"` and
     `binding_strength: "none"` with an explicit warning.
   - Missing receipt: keep `scope: "missing_receipt"` and
     `binding_strength: "none"`.
7. Update docs and CLI help for `docs/code-context.md`,
   `docs/context-pack.md`, and relevant tests.

## Invariants (what to protect, on the normal paths)

- Binding is recorded in lockstep: when a target flag is given, the receipt
  evidence row, its `evidence_links` `code_context` row, and the artifact
  `target_binding` are written in one transaction and must agree. Never write
  the link row without the receipt, or an artifact `target_binding` without the
  link row.
- Binding is a **caller assertion**, not PLH proof that the receipt is
  semantically relevant. Use claims-not-facts vocabulary; do not add fields such
  as `safe_to_continue`, `verified_relevant`, or `agent_read`.
- Extend `impact/v0`, `context-receipt/v0`, and `context-pack/v1` **additively**
  via the `code-context-summary/v0` insulation layer (0078). The pack embeds the
  summary and `receipt_ref` (evidence_id / receipt_path) only — never the full
  receipt body or copied evidence contents.
- `pcl context pack` remains read-only: it must not run `pcl index build`,
  `pcl impact`, Git commands, tests, or any artifact-generating command. It
  reads `evidence_links` and evidence rows only.
- `source_commands` remain read-only re-fetch commands. Artifact-generating
  commands (`pcl impact …`) appear only under `suggested_refresh_commands`.
- Existing unscoped latest behavior remains available when
  `--require-bound-receipt` is absent.
- Deterministic generated artifacts stay deterministic; timestamped facts remain
  in receipt/evidence payloads where timestamps already exist.

## Non-scope

- Semantic or embedding-based relevance proof.
- Automatic target inference from changed files, branches, or task text.
- `pcl context pack --receipt ...` manual receipt selection.
- `pcl receipt list` / `pcl evidence link` CLI verbs.
- Dashboard redesign or MCP surface changes.
- Hosted code analysis, cloud sync, telemetry, or external LLM calls.
- `pcl context check` preflight (deferred to v0.3.1).

## Acceptance

- `pcl impact --diff --for-task T-0001 --json` writes a receipt with
  `target_binding.target_type == "task"` and `target_id == "T-0001"`, and an
  `evidence_links` row `(target_type="task", target_id="T-0001",
  link_role="code_context")`.
- `pcl impact --diff --for-job J-0001 --json` writes a receipt with
  `target_binding.target_type == "agent_job"` and `target_id == "J-0001"`, and
  the matching `code_context` link row.
- Invalid target IDs and mutually exclusive target flags fail with typed errors
  before any evidence or link row is created.
- `pcl context pack --task T-0001 --include-code-context --json` chooses the
  newest matching task-bound receipt over a newer unbound receipt, via the
  `evidence_links` query.
- `pcl context pack --job J-0001 --include-code-context --json` chooses the
  newest matching job-bound receipt over a newer unbound receipt.
- Without a matching bound receipt and without `--require-bound-receipt`,
  context pack still succeeds with the existing unscoped latest warning and a
  target-specific suggested refresh command.
- With `--require-bound-receipt` and no matching bound receipt, context pack
  fails with `context_pack_bound_receipt_required` and does not silently fall
  back to unscoped latest.
- `source_commands` for code-context packs still contain only read-only
  commands; `pcl impact` appears only under `suggested_refresh_commands`.
- Full `pytest` green.
- Live smoke in a scratch project:
  1. `pcl init`
  2. create a goal and task
  3. `pcl index build --json`
  4. make a small tracked change
  5. `pcl impact --diff --for-task T-0001 --json`
  6. `pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json`
  7. `pcl validate --strict --json`
  8. `pcl render --json`
