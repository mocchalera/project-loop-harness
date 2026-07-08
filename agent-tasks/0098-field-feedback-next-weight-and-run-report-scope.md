# Task 0098: Field Feedback — `pcl next` Recommendation Weight + Run Report Record Scope

Origin: Cockpit task 0c7d3d85 (kikulab-design, Codex gpt-5.5). An
implementation agent ran a full mockup-to-code job under the
project-control-loop skill and reported structured feedback. The
documentation-side items (direct implementation loop template,
workflow close-out procedure, human-gate stop rule, `pcl.yaml`
`commands.*` clarification) were applied to
`skills/project-control-loop/SKILL.md` and synced to all
distribution copies. Two items are product behavior, not docs, and
are tracked here.

## Problem A: `pcl next` recommends a workflow run for every open goal

Observed in kikulab-design and reproduced in this repo: with one open
goal and no open defects, `pcl next` returns
`pcl loop run feature_coverage --goal G-XXXX` (priority 60,
`continue_goal`). For a single direct implementation task this is
heavier than needed: it creates mapper/story/test_designer queued
jobs the agent must later produce outputs for and ingest, and ends in
a human-gated `verification record` for the run.

The field agent followed the recommendation literally and only later
realized the minimal feature/story/test path would have sufficed.

### Direction (design before code)

- `pcl next` should distinguish "goal has no feature/story/test
  activity at all" (workflow suggestion is reasonable) from "goal has
  in-flight direct work" (suggest continuing the feature/story/test
  path instead).
- Alternatively or additionally: include an explicit
  `alternative` field in the `pcl next` JSON pointing at the minimal
  direct-implementation path, so agents can choose deliberately. The
  skill now documents the choice; the CLI should not fight it.
- Keep `safe_to_run: false` semantics unchanged.

## Problem B: `pcl report run WR-XXXX` shows "No records" for existing features/stories/tests

Observed: after F-0001 / US-0001 / TC-0001 existed and jobs were all
passed, the run report still rendered Features / User Stories / Test
Cases sections as "No records". The records existed in the project;
they were simply not linked to the workflow run. To a reader the
report looks like the work does not exist.

### Direction (design before code)

- Decide the intended scope of the run report sections: run-linked
  records only, or run-linked plus goal-scoped records.
- If run-linked only: label the sections accordingly ("No records
  linked to this run") and consider linking records created during
  the run window or referenced by ingested agent outputs.
- Add a pointer line to the goal-level totals so an empty section is
  never mistaken for an empty project.

## Non-goals

- No change to human-gate semantics for run verification (the gate is
  correct; the skill now tells agents to stop and report it).
- No autonomous verification recording.

## Definition of done

- Design note agreed for A and B (may be one doc).
- Implementation + tests green (`python3 -m pytest`).
- Live smoke against a scratch project showing (a) `pcl next` output
  for a goal with in-flight direct work, and (b) a run report whose
  empty sections are self-explanatory.
- Evidence paths for all claims.
