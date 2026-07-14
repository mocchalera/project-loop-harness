# 0168: Structured command guide

- **Status:** In progress
- **Milestone:** v0.5.0 Adoption / Distribution
- **Priority:** P1
- **Size:** M
- **Dependencies:** 0167
- **DB schema:** no change
- **Human approval:** structured `pcl guide --json` option approved in Cockpit on 2026-07-14

## User problem

The corrected 30-day local Skill usage report observed 768 help probes across
93 sessions. The largest cluster was the root help family with 117 probes in
60 sessions, followed by repeated lookups for Evidence, Feature, Story, Test,
and terminal-transition syntax.

The existing argparse help is accurate, but it is organized by command tree.
An agent that knows its purpose (start work, follow the direct route, finish,
review the dashboard, or recover) must still visit multiple help pages and
reconstruct the lifecycle order itself.

## Product outcome

`pcl guide` provides one deterministic, read-only, initialization-independent
surface for purpose-oriented lifecycle guidance. `pcl guide --json` returns
all topics; `pcl guide TOPIC --json` returns one topic. The bundled Project
Control Loop Skill routes genuine route or syntax uncertainty to this guide
before probing multiple argparse help pages.

## Scope

1. Add a `command-guide/v1` contract with a stable ordered topic list.
2. Cover `start`, `direct`, `finish`, `dashboard`, and `recover` purposes.
3. Give every step an ordered command template, mutation flag, run policy,
   required substitutions, purpose, and expected outcome.
4. Support a concise deterministic text rendering when `--json` is absent.
5. Return the standard typed `invalid_input` JSON error for an unknown topic,
   including the supported topic list.
6. Keep the command usable outside an initialized project and prove it does
   not create `.project-loop` state.
7. Update the bundled Skill to prefer one guide lookup when route or syntax is
   unclear; routine direct-route work should continue without an extra call.
8. Document the new surface and update the committed root-help baseline.

## Contract shape

```json
{
  "ok": true,
  "contract_version": "command-guide/v1",
  "requested_topic": null,
  "topics": [
    {
      "topic": "start",
      "purpose": "...",
      "steps": [
        {
          "order": 1,
          "command": "pcl init --dry-run --json",
          "mutates_state": false,
          "run_policy": "agent_safe",
          "requires": [],
          "purpose": "...",
          "expected_after": "..."
        }
      ]
    }
  ]
}
```

`run_policy` is either `agent_safe` or `human_required`. Command templates use
angle-bracket placeholders and declare each placeholder in `requires`.

## Acceptance

1. `pcl guide --json` returns all five topics in stable order before project
   initialization and leaves the target directory unchanged.
2. `pcl guide direct --json` returns only `direct`, with sequential steps from
   `pcl start` through strict validation/rendering and explicit human approval
   metadata for Story approval.
3. An unknown topic returns exit code 2 with the normal `invalid_input` JSON
   envelope and the supported topics.
4. Text and JSON output are byte-deterministic for identical invocations.
5. Every guide command uses current canonical flags, including
   `--evidence-id`, `pcl finish --emit-packet`, and `pcl goal close`.
6. The bundled Skill mentions `pcl guide --json` and topic-specific lookup as
   the preferred fallback for route or syntax uncertainty.
7. Focused tests, baseline fixtures, `ruff check .`, full `pytest`, strict PCL
   validation, rendering, and completion-packet closure pass.

## Non-goals

- Replacing normal `pcl next --json` routing.
- Dynamically generating command templates from argparse internals.
- Executing guide steps, mutating project state, or approving human gates.
- Changing existing command syntax or error behavior.
- Adding dependencies, migrations, network access, telemetry, or hosted state.
