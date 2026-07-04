# Task 0070: Human Decision Cockpit (P1.5)

## Goal

Reduce human decision friction. The dashboard and `dashboard-data.json` must
let the primary persona — an AI-development power user directing multiple
agents, not necessarily reading code — answer in one glance: why is the loop
stopped, what are the safe next options, what are their risks, what is
recommended, which command runs it, and which evidence backs it.

## Scope

- Extend the dashboard-data contract additively: each human decision item
  carries `why_blocked`, `options[]` (each with label, command, `why_safe`,
  `risk_if_run`), a recommendation with reason, and related evidence paths.
  Receipt paths are an optional field, populated once task 0069 lands; this
  task must not depend on 0069.
- Render a prominent "Needs Your Decision" section in the HTML dashboard
  built from those fields; the HTML stays human-only.
- Give reject, hold, and request-more-evidence options equal visual weight
  with approve — no approval-biased presentation.
- Extend `--locale ja` coverage to the new section and any remaining
  untranslated dashboard chrome.
- Align `pcl next --json` output with the new option fields where a human
  decision is the next action.

## Acceptance Criteria

- Contract evolution follows the existing dashboard-data policy (additive
  fields on v1, documented in `docs/dashboard-data-contract.md`).
- Rendering is deterministic; repeated renders over the same state are
  byte-identical.
- Japanese locale output is covered by tests for the new section.
- Decisions, escalations, and needs-human verifications all surface in the
  section with their options.
- `ruff check .` passes.
- Full `python3 -m pytest` passes.
- `pcl init` smoke flow against a temp directory passes.
- No schema migration is added.
- No dependency is added.

## Do Not

- Do not build a web app, server, or interactive buttons that execute
  commands; the dashboard remains a generated static view.
- Do not make dashboard HTML machine-readable context; agents keep using
  `dashboard-data.json` and context packs.
- Do not add or alter tables or columns.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, paid services, or plugin
  distribution.
