# 0139: executable restart context for `pcl resume`

- **Status:** Approved repair for `D-0001` / `F-0006`
- **Milestone:** v0.4.0 Three-command Wedge exit repair
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** 0135 and 0137 merged
- **Evidence:** `E-0050` (Yohaku Dorobo real-task blind replay)

## Problem

The first real `start -> finish --emit-packet -> resume` dogfood produced a
valid handoff packet quickly, but a fresh Codex reviewer judged it **NOT
USEFUL** as a standalone restart packet. It exposed `DONE`, the completion
outcome, revision, claims, and Evidence IDs, but did not expose a public way to
resolve those IDs or the concrete commands behind the verified finish checks.
For terminal targets, `next_safe_action.command` was `null` even though the
completion packet already contained reproducible passed commands.

The reviewer consequently had to inspect package scripts and explore the CLI.
This fails the cross-session replay acceptance criterion in 0137 and blocks
G-0007.

## Goal

Make a generated `handoff-packet/v1` executable enough for a fresh session to:

1. identify the acceptance target without prior chat;
2. resolve every surfaced Evidence ref through a documented read-only command;
3. rerun at least one verified check directly from the packet;
4. find bounded project-documentation and changed-path context without inlining
   evidence bodies or full transcripts.

## Scope

### 1. Read-only Evidence metadata command

Add:

```text
pcl evidence show E-XXXX [--json]
```

The command returns stable metadata already held by Project Loop: Evidence ID,
type, summary, claimed command, recorded path, creation time, and, for supported
manifest-backed Evidence, member/stored paths and hashes. It must not inline
artifact bodies, execute the claimed command, or mutate DB/events/outbox/files.
Unknown IDs return a typed input error.

### 2. Additive `handoff-packet/v1` restart context

Add an optional top-level `restart_context` object. Old valid v1 packets without
this field remain valid. Generated packets include it with deterministic,
bounded ordering:

- `target_intent`: factual task description/title or goal title;
- `acceptance_status`: `intent_only`, `work_brief_linked`, or `missing`;
- `acceptance_ref`: the target work brief ref when one is actually recorded;
- `target_review_command`: `pcl task read ... --json` or the corresponding goal
  report command;
- `verification_commands`: deduplicated reproducible completion checks, keeping
  command, previous status, Evidence refs, and proof source;
- `evidence_resolution_commands`: one `pcl evidence show ... --json` command per
  referenced Evidence ID;
- `changed_paths`: bounded paths from the selected completion packet;
- `documentation_candidates`: bounded changed files whose basename is an
  established project documentation shape such as `README*`, `CONTRIBUTING*`,
  or files under `docs/`. These are navigation hints, not verified acceptance
  facts.

The contract must distinguish missing acceptance detail from verified facts. It
must never infer a launch URL, claim a documentation candidate is authoritative,
or promote a generic Evidence summary into `verified`.

### 3. Executable next safe action

For a terminal target with a valid completion packet, use the first
deterministically ordered reproducible passed check as
`next_safe_action.command`. If none exists, fall back to the existing review-only
action with `command: null`. Open human decisions and explicit completion
`next_action` continue to take precedence.

### 4. Markdown and docs

Render the restart context from the JSON packet. JSON remains the source of
truth. Document Evidence metadata lookup and the trust boundary: commands are
replay instructions sourced from the completion packet, not newly executed
facts.

## Invariants

- `pcl resume` and `pcl evidence show` are fully read-only.
- No evidence body or full transcript is inlined.
- No shell command is invented from package files; replay commands come only
  from the selected completion packet.
- No acceptance criteria are invented. `intent_only` is explicit when no
  work-brief link exists.
- Existing `handoff-packet/v1` fixtures remain valid.
- Deterministic order, content-derived packet ID, metrics, and size bounds remain
  intact.
- No schema migration, dependency, LLM call, agent launch, or remote operation.

## Acceptance criteria

- `pcl evidence show` resolves completion-packet and completion-check Evidence
  metadata and has read-only fingerprint assertions.
- A real-shaped completion packet yields deterministic verification commands,
  Evidence resolution commands, target intent, changed paths, and README/docs
  candidates.
- A terminal resume packet exposes a non-null replay command when a reproducible
  passed check exists.
- A fresh-session integration test uses only `pcl resume` output and public CLI
  commands from the packet to resolve Evidence and rerun a documented check.
- Missing work brief remains explicit `intent_only`; it is not represented as a
  complete acceptance specification.
- Markdown and JSON preserve identical verified/unverified and restart-command
  semantics.
- Old handoff fixture validation, packet tamper checks, finish compatibility,
  ruff, targeted tests, and the full pytest suite pass.

## Agent execution protocol

Before editing, characterize the Yohaku Dorobo failure in `E-0050`, the existing
completion-packet check shape, Evidence table/manifest variants, and current
read-only fingerprint tests. Keep changes to the smallest contract/CLI/docs/test
surface required here.

At completion, report the commit SHA, changed files, exact test commands/counts,
sample JSON for `pcl resume` and `pcl evidence show`, read-only proof, backward
compatibility proof, and unresolved limitations. Do not push or merge.
