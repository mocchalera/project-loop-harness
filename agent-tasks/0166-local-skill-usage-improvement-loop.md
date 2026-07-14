# 0166: Local Skill usage improvement loop MVP

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P1
- **Size:** L
- **Dependencies:** 0165
- **DB schema:** no change
- **Human approval:** local telemetry collection approved in the 2026-07-14 Cockpit conversation

## User problem

Project Loop Harness is already dogfooded across Codex, Claude, and Cockpit, but
the maintainer has to reconstruct recurring friction manually from large raw
session logs. The machine has enough evidence to identify whether the bundled
Skill was actually read, which `pcl` command families were executed, and which
typed failures or retries recurred. Blindly copying those logs would retain
prompts, file contents, command arguments, and other sensitive material.

## Product outcome

`pcl report skill-usage` performs an explicit, local, read-only scan of existing
Codex, Claude, and Cockpit JSONL logs. It emits aggregate usage and friction
metrics plus deterministic improvement candidates without retaining raw
conversation text, command arguments, workspace paths, or external data.

## Scope

1. Add `pcl report skill-usage` with `--since`, `--until`, repeatable `--source`,
   source-root overrides for fixtures/custom installs, and optional `--output`.
2. Default to a 30-day local window and the conventional Codex, Claude, and
   Cockpit log roots under the current home directory.
3. Stream JSONL records. A malformed line increments a source-level parse count
   and does not disclose the line or path.
4. Count actual Skill use only from execution signals: Codex shell reads of
   `project-control-loop/SKILL.md`, Claude `Skill`/`Read` tool calls, and explicit
   Cockpit skill directives. Merely listing an available Skill is not use.
5. Extract only normalized `pcl` command families/subcommands from actual Codex
   execution calls and Claude Bash tool calls. Never retain arguments or raw
   command text.
6. Classify a small typed friction vocabulary from tool results: command error,
   timeout, missing finish checks, guarded execution block, and completed with
   risk. Also count help probes and repeated normalized command families.
7. Keep Cockpit control-plane task signals separate from Codex/Claude agent
   sessions so the aggregate does not double-count mediated executions.
8. Return a stable `skill-usage-report/v1` JSON contract and deterministic
   Markdown rendering. Optional output uses atomic replacement.
9. Emit deterministic, evidence-counted improvement candidates. The report
   never edits the Skill, creates PCL state, or applies a recommendation.
10. Document the privacy boundary, limitations, and the human-reviewed
    report-to-fixture-to-regression improvement loop.

## Invariants

- No dependency, database migration, hosted service, network request, daemon,
  background watcher, or external transmission.
- The scan and default stdout path do not mutate `.project-loop` state or append
  events.
- Raw prompts, assistant messages, tool output, command arguments, session IDs,
  task IDs, absolute log paths, and workspace paths never appear in the report.
- Source unavailability is factual and non-fatal; an explicitly malformed date
  or unknown source is a typed input error.
- The report does not claim that an inferred command error proves a product
  defect. Improvement candidates remain advisory until reproduced as tests.
- Existing `pcl report kpi` behavior and contracts stay unchanged.

## Acceptance

1. Codex fixture: available-Skill catalog text alone is ignored; an actual
   `SKILL.md` read is counted.
2. Claude fixture: `Skill`/`Read` and Bash tool calls produce one deduplicated
   session with normalized command counts.
3. Cockpit fixture: repeated reports for one task produce one control-plane task
   signal and are excluded from agent-session totals.
4. JSON output contains aggregate counts, privacy declarations, source health,
   friction signals, and evidence-counted improvement candidates only.
5. Markdown and JSON contain none of the fixture secrets, commands, arguments,
   IDs, raw paths, or workspace names.
6. `--since`/`--until`, source selection, missing roots, malformed JSONL, and
   invalid input are covered.
7. The command is read-only for project DB/events and source logs; `--output`
   changes only the requested report file and is byte-deterministic.
8. Real-machine dogfood completes for the approved window and reports source
   counts without leaking raw log content.
9. Focused tests, `ruff check .`, full `pytest`, strict PCL validation, and the
   rendered dashboard pass.

## Non-goals

- Continuous monitoring, launch agents, cron jobs, or file watchers.
- Uploading usage data, identifiers, prompts, or reports.
- Cross-machine analytics or user tracking.
- Automatic Skill edits, issue creation, prioritization changes, or release
  decisions.
- Exact reconstruction of every shell pipeline or model-specific transcript.
- Schema changes or persistence of per-session records.
