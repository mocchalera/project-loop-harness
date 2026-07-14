# 0172: Composite PCL result status

- **Status:** Complete
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** S
- **Dependencies:** 0166, 0167, 0170
- **DB schema:** no change
- **Human approval:** Story US-0032 approved in Cockpit task 482dd44e on 2026-07-14

## User problem

A successful shell tool call can contain several PCL JSON results, non-PCL
preamble, or a truncated long JSON result. The Skill usage report previously
treated that supported successful wrapper as unknown and scanned incidental
words in Goal titles, Story expectations, command-guide examples, and stored
Evidence as fresh friction.

## Product outcome

`pcl report skill-usage` recognizes supported successful composite Codex
results before classifying their text. Descriptive or historical wording does
not create new friction, while explicit failures and typed
`COMPLETED_WITH_RISK` outcomes remain visible.

## Scope

1. Parse one or more complete whitespace-separated PCL JSON results.
2. Parse standalone compact JSON results after a non-PCL preamble.
3. Treat any parsed top-level `ok:false` as failure.
4. Treat a complete one-result-per-command JSON sequence as success.
5. Recognize the supported Codex `Script completed` wrapper when a long PCL
   output is truncated before its JSON can be parsed.
6. Preserve typed completion-outcome extraction across composite JSON.
7. Re-run the frozen 2026-07-14 local dogfood window.

## Invariants

- No raw content, command arguments, identifiers, or paths enter the report.
- Explicit `ok:false`, failed wrappers, non-zero process status, and Claude
  `is_error:true` remain failures.
- Unknown wrappers without supported success evidence retain best-effort text
  classification.
- Command counts and `skill-usage-report/v1` remain compatible.
- No dependency, migration, network request, telemetry, or automatic action.

## Acceptance

1. Multiple successful PCL JSON results containing friction vocabulary emit no
   failure friction.
2. A composite result containing `ok:false` still emits command-error and
   matching typed friction.
3. A successful truncated Codex wrapper does not classify stored descriptive
   text as a new failure.
4. A typed `COMPLETED_WITH_RISK` inside successful composite JSON is retained.
5. Focused tests, lint, full tests, strict validation, rendering, and the local
   dogfood rerun pass.

## Non-goals

- Reconstructing exact stdout boundaries for every shell pipeline.
- Inferring success for unknown adapters.
- Changing improvement-candidate priorities or automatically applying them.
