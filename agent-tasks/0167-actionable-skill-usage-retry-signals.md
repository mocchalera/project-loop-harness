# 0167: Actionable Skill usage retry signals

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P1
- **Size:** M
- **Dependencies:** 0166
- **DB schema:** no change
- **Human approval:** first data-driven improvement cycle requested in the 2026-07-14 Cockpit conversation

## User problem

The first real-machine `pcl report skill-usage` run reported 4,339 repeated
commands across 95 sessions. The current calculation counts every second and
later use of a normalized command anywhere in a session. That includes the
intentional `validate`, `render`, and `next` cadence required by the bundled
Skill, so the highest-ranked improvement signal is dominated by expected work.

The report also aggregates friction only by type. It cannot show which safe,
normalized command families contributed to a timeout, command error, help
probe, or retry without returning to raw transcripts.

## Product outcome

The local report counts a repeated command only when it is the next detected
PCL command after a failed PCL call and the normalized command family matches.
Friction rows include deterministic normalized command breakdowns so a human
can select a reproducible improvement without exposing arguments, paths, IDs,
or raw output.

## Scope

1. Preserve the additive `skill-usage-report/v1` contract and existing summary
   fields.
2. Associate each supported PCL tool result with the normalized command
   families from its call ID.
3. Attribute typed output friction to those normalized commands.
4. Replace session-wide duplicate counting with failure-driven retry counting:
   only the next detected PCL call after an error/timeout/guarded block is a
   retry candidate, and only matching normalized command families count.
5. Attribute help probes directly to their normalized command family.
6. Add sorted command breakdowns to friction rows and include the leading
   command family in advisory candidate Evidence when available.
7. Keep Cockpit signals separate and preserve all 0166 privacy/read-only
   boundaries.
8. Re-run the frozen 2026-06-14 through 2026-07-14 dogfood window and compare
   the corrected signal with the 0166 baseline.

## Invariants

- No raw command, argument, output, prompt, path, identifier, or workspace name
  appears in JSON or Markdown.
- Only labels accepted by the existing normalized PCL command allowlist may
  appear in a command breakdown.
- Routine repeated lifecycle commands without a preceding classified failure
  are not friction.
- A failure followed by a different PCL command is not a matching retry.
- Unknown or missing call IDs do not create command attribution.
- No dependency, database migration, network request, external transmission,
  daemon, background watcher, automatic state change, or Skill rewrite.
- JSON and Markdown remain byte-deterministic for identical fixtures.

## Acceptance

1. A fixture that runs `validate`, performs other work, then runs `validate`
   again produces no `repeated_command` signal.
2. A failed normalized command followed by the same normalized command
   produces one matching retry; a different next command produces none.
3. Command errors, timeouts, guarded blocks, completed-with-risk results, and
   help probes expose only deterministic normalized command breakdowns.
4. Advisory candidate Evidence includes the leading normalized command and its
   counts when attribution exists.
5. Codex and Claude fixtures cover call-ID attribution and missing/unknown call
   IDs without leaking raw content.
6. JSON and Markdown privacy assertions, source fallbacks, deterministic output,
   and read-only checks continue to pass.
7. The same real-machine date window completes locally and materially reduces
   the false-positive repeated-command baseline while preserving factual typed
   friction signals.
8. Focused tests, `ruff check .`, full `pytest`, strict PCL validation, and
   rendering pass.

## Non-goals

- Proving that every attributed error is a product defect.
- Retaining sanitized transcript excerpts or command arguments for drilldown.
- Automatically opening Issues, editing the Skill, or changing priorities.
- Session timelines, per-session exports, or cross-machine analytics.
- Time-based causal inference across arbitrary non-PCL agent actions.
