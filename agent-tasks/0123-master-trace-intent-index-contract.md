# 0123: Master Trace / Intent Index v0 contract formalization

Milestone: v0.3.2 Master Trace / Intent Index
Priority: P1
Area: docs/contracts/handoff
Origin: M0 master-trace dogfood, `docs/growth-plan-v0.2.4-v0.5.md`, and
2026-07-09 AI-PLC upstream-design intake discussion. Sakamoto approved moving
ahead after migrating the local control-plane DB to schema 7.

## Problem

Project Loop Harness already has a working M0 pull-context handoff runbook:
the master transcript is copied as evidence, an external agent creates an
intent index over that transcript, and the worker starts from `pcl next` plus a
task context pack. That flow proved useful, but the contract is still
runbook-shaped rather than product-shaped.

The AI-PLC proposal adds a larger upstream layer: collection, intent, option
generation, replan, maker/checker separation, and knowledge propagation. PLH
should not import that as slash commands or Markdown state. The first safe
translation is narrower: formalize master traces and intent indexes as
evidence-backed, claims-not-facts handoff contracts that can later support
first-class `pcl intent` / `pcl option` work if dogfood proves the shape.

## Scope

Docs/contract first. No schema migration and no new state-changing CLI command
in this slice.

1. Add a contract document, preferably `docs/master-trace-intent-index.md`,
   covering:
   - `master-trace/v0`: a transcript or trace artifact recorded as copied
     evidence, with stable line references after indexing.
   - `intent-index/v0`: a model-derived JSON index whose items are pointers into
     the master trace, not verified facts.
   - `master-trace-context/v0`: the future context-pack section shape, listing
     evidence ids, manifest/member paths, copied stored paths, and source-ref
     discipline without inlining raw transcript contents.
2. Update `docs/master-trace-handoff.md` so M0 is clearly a historical dogfood
   runbook and points to the new contract for future runs.
3. Document the recommended current command sequence using existing surfaces:
   `pcl evidence add --copy`, `pcl evidence add --task T-XXXX --copy`,
   `pcl context check`, and `pcl context pack --task ...`.
4. Define the precise trust model:
   - the intent index is model output and must be treated as claims, not facts;
   - a worker must verify every actionable item against copied trace lines before
     acting;
   - PLH records evidence and links, but does not claim the index is correct,
     complete, safe, or semantically sufficient.
5. Add an explicit "future promotion gates" section:
   - optional `master_trace_context` in `context-pack/v1` is a follow-up only
     after this contract is accepted;
   - first-class `pcl intent` / `pcl collect` requires separate design and human
     approval because it adds product semantics and likely schema;
   - `pcl option`, `pcl replan`, and knowledge ledger are later phases, not part
     of v0.3.2.

## Invariants

- No LLM call in `pcl` core. External agents may produce an intent index; PLH
  stores and routes the artifact as evidence.
- No new source of truth. SQLite + JSONL events remain authoritative; Markdown
  docs and future wiki exports are review surfaces.
- No raw transcript inline in context packs or dashboard data. Use evidence ids,
  manifest paths, member paths, and copied `stored_path` references.
- No cognition or go/no-go vocabulary: avoid `safe_to_continue`,
  `verified_relevant`, `agent_read`, `ready_for_handoff`, or similar claims.
- Existing `linked_evidence` task-pack behavior remains unchanged in this slice.
- Do not add `pcl intent`, `pcl collect`, `pcl option`, `pcl replan`, or
  `pcl knowledge` commands in this task.

## Non-scope

- Schema changes or migrations.
- `pcl evidence link` / arbitrary link-role CLI.
- Context-pack implementation of `master_trace_context`.
- Dynamic workflow generation.
- Hosted backend, telemetry, cloud sync, or plugin marketplace work.
- Automatic GitHub writes or any external-service dependency.

## Acceptance

- The new contract doc defines valid `master-trace/v0`, `intent-index/v0`, and
  future `master-trace-context/v0` payload examples.
- `docs/master-trace-handoff.md` points future readers to the contract while
  preserving the M0 evidence/runbook history.
- The current command sequence is executable with existing commands and does not
  require direct DB edits or generated dashboard parsing.
- The docs state that intent-index items are navigation pointers, not verified
  facts, and that workers must verify source refs against copied trace lines.
- The docs explicitly defer first-class `pcl intent` / `pcl option` / `pcl
  replan` / knowledge ledger work to later roadmap phases.
- `ruff check .` and full `pytest` remain green unless the orchestrator marks
  the task docs-only and records why test execution was intentionally skipped.
