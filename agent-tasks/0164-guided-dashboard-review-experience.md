# 0164: Guided dashboard review experience

- **Status:** Implementation complete; final Claude review pending
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P0
- **Size:** M
- **Dependencies:** 0163
- **DB schema:** no change

## User problem

The dashboard is available but passive: operators do not know when to open it,
agents do not present it at review-worthy moments, and the first screen exposes
control-plane vocabulary before answering the operator's basic questions. The
existing Japanese locale is also easy to miss because a normal `pcl render`
falls back to English when `dashboard.locale` is not configured.

## Product outcome

An operator can supervise Project Loop without learning its internal entity
model. At meaningful milestones the agent renders and presents the dashboard,
states what to inspect, and the first screen answers five questions in the
operator's language:

1. What is happening now?
2. What was just completed?
3. What happens next?
4. Is a human decision required?
5. What risk or warning remains?

## Scope

### Runtime and dashboard

- Add a localized operator-summary block above counters and diagnostic panels.
- Derive the summary from existing state only; do not create a second source of
  truth or let agents parse dashboard HTML.
- Keep the stable `dashboard-data/v1` machine contract byte-for-byte unchanged;
  the operator summary is derived at HTML render time only and never enters
  `dashboard-data.json`.
- Derive `Done` exclusively from evidence-backed terminal transitions: Feature
  done with Evidence, Test pass with Evidence, Goal closed with closure proof,
  or approved Verification. Reason-only Task completion is not presented as
  verified. `Done` is a pure function of current state with no "since last
  viewed" semantics.
- Localize summary sentences by composing structured fields with per-locale
  templates. Japanese summary text must not embed pre-built English `summary`,
  `why_blocked`, `reason`, or `recommendation_reason` strings.
- Move counters, raw commands, queues, and entity tables under an explicitly
  labeled advanced-details disclosure while preserving every existing review
  surface.
- Use native `<details>/<summary>` only. Generated HTML remains script-free and
  existing `#row-...` links and `id="row-..."` targets remain present.
- Configure this repository to retain Japanese dashboard chrome across normal
  `pcl render` calls.

### Agent behavior

- Update every bundled Project Control Loop Skill copy with one host-neutral
  presentation rule that distinguishes rendering from presenting: render
  silently after normal validation; present only at the four review moments.
- Present the dashboard after plan approval, at a major milestone, when a human
  decision blocks progress, and after goal closure.
- If the host has a visual/file side panel, open the generated dashboard there;
  otherwise provide the path. Always state the review focus in plain language.
- Do not interrupt the user or open the dashboard after every routine mutation.

### Documentation

- Explain the simple operator view, advanced details, locale persistence, and
  the four presentation moments in README/adoption guidance.

## Invariants

- SQLite remains the source of truth; generated HTML stays human-only.
- No database migration, dependency addition, telemetry, hosted UI, browser
  automation dependency, or Cockpit-specific runtime coupling.
- Locale changes affect HTML presentation only; machine JSON remains stable.
- A dashboard presentation never approves a Story, Verification, Decision, or
  other human gate.
- Detailed evidence, commands, and diagnostics remain inspectable.
- Rendering remains deterministic for unchanged state.

## Acceptance

1. Japanese rendering opens with localized `Now / Done / Next / Human needed /
   Risks` guidance before counters or internal tables.
2. The summary accurately distinguishes agent-safe continuation, human-gated
   work, idle state, validation warnings, and goal closure without asserting
   unverified success. `Done` entries name their Evidence or closure proof, and
   reason-only completion is never presented as verified.
3. Existing detailed panels remain present under progressive disclosure.
4. This repository's ordinary `pcl render` produces `<html lang="ja">`.
5. All bundled Skill copies define the same four presentation moments and the
   same host-neutral open-or-link fallback.
6. Tests cover summary states, localization, deterministic output, Skill parity,
   and the preserved `dashboard-data/v1` contract.
7. The generated dashboard is visually inspected in Cockpit at desktop and
   narrow widths, including confirmation that `#row-...` navigation keeps
   targets reachable inside advanced-details disclosure.
8. Claude Fable reviews the plan and final implementation; required findings
   are resolved before closure.

## Non-goals

- Interactive mutation buttons in static HTML.
- Translating user-authored titles, Evidence, commands, or machine JSON values.
- Replacing reports, Context Packs, or `pcl next`.
- Redesigning the full visual language or adding a hosted dashboard.
