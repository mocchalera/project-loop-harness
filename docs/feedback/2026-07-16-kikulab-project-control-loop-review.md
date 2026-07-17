# kikulab-design Project Control Loop Field Review

**Source:** Cockpit task `9649a8d2`, read-only review of the Listening Care LP
work in `/Users/mocchalera/Dev/kikulab-design`.

## Verdict

Project Loop was useful as acceptance-history memory, but it was not a reliable
current-work navigator or closeout gate in this run. The strongest success was
preserving a user correction. The largest failures were stale agent
instructions, global `next` routing to another project slice, and mutable
evidence paths that drifted after registration.

## Findings by severity

### P0: The installed Skill was stale and the runtime did not report it

The adopter's `.agents/skills/project-control-loop/SKILL.md` predated the
Evidence-ID-first direct route. It still recommended inline `--evidence`, did
not link planned Tests to Stories, omitted `pcl start`, and had no current-intent
or immutable-artifact rule. Normal `pcl init --dry-run --json` unconditionally
reported the existing Skill as `skip`, so later Skill improvements could not
reach the project.

### P0: `pcl next` represented global unfinished state, not the active LP work

The current implementation work was `F-0009`, but `pcl next` returned the older
`F-0008 Listening Work Lab clean-room LP v3`. The selection was internally
consistent with global priority ordering, but operationally misleading because
there was no explicit session/Goal/Feature focus. An agent following the command
would leave the user's current intent.

### P0: Ten registered Evidence sources drifted after report-path reuse

`pcl audit check --json` found ten source hash mismatches. The database and
event projection were not corrupt; verification reports were regenerated into
paths that earlier Evidence manifests had already hashed. Examples included
re-registering the same verification reports minutes later and reusing a
`reapply-verification.md` path. Durable copies could remain healthy while the
source paths drifted, but the run no longer had a clean closeout signal.

### P1: Strict validation and audit health gave conflicting completion signals

The review observed normal `doctor` / `validate --strict` success alongside a
failing `audit check`. Validation did not distinguish active completion proof
from superseded historical source drift, so neither command alone answered
"is current completion proof healthy?".

The final review measured ten mismatches across seven Evidence records. It also
confirmed that some were already superseded (`E-0026 -> E-0028 -> E-0029 ->
E-0032`) and that copied bytes remained available. The runtime therefore needs
to distinguish current proof corruption, mutable-source drift with a healthy
copy, and superseded historical drift.

### P1: Configured QA could pass without reading the active LP

The adopter's `pcl.yaml` verification commands targeted `work/site/index.html`
and `work/manifest.json`, while the active surface was
`work/listening-care-lp-20260712`. Missing-path fallbacks could still exit zero.
PCL Tests captured useful visual results, but the configured QA did not prove
that it inspected the active LP. Product Feature `F-0009` and shared-Skill
Feature `F-0010` also diverged as later typography, section-connection, image,
and sprite lessons were applied.

### P1: Direct closeout still required too much manual composition

Feature, Story, Test, Evidence, Evidence Set, completion policy, Task, packet,
and Goal surfaces existed, but the safe direct route remained easy to execute
partially. This encouraged state that documented work without clearly closing
the current work.

## What worked

The user corrected the acceptance meaning of the yellow-line decoration. The
agent preserved the original `TC-0020`, waived it with a reason, and created the
corrected `TC-0021`. That retained who changed the expectation and prevented a
false history in which the original acceptance condition appeared never to
have existed. This is the behavior the Skill should teach explicitly.

## Implemented in 0191

- `pcl doctor` detects a project-local Skill that differs from the running
  package and returns typed targeted-refresh guidance.
- `pcl init --refresh-skill` previews and updates only the Skill, stores the
  replaced bytes in a SHA-256-addressed backup, and appends an audit event.
- The Skill stops before executing a `pcl next` target unrelated to the current
  user intent and registers explicit separate work with `pcl start --new`.
- Registered Evidence source paths are write-once; reruns use a new artifact and
  Evidence ID.
- Human-corrected acceptance conditions use waive plus replacement rather than
  semantic rewriting.
- Review-only requests stay read-only and skip render/report generation unless
  explicitly requested.
- Configured QA must target the active Feature surface, and durable PCL Tests
  are reserved for semantic corrections and reproducible contracts rather than
  every small CSS adjustment.

## Follow-up runtime backlog

1. Add explicit `pcl next` scoping (`--goal`, `--feature`, or a session focus)
   and explain excluded candidates.
2. Warn when `pcl evidence add` reuses a path referenced by existing Evidence;
   offer a versioned path or explicit supersession flow.
3. Classify audit findings by active completion impact: current durable-copy
   corruption, current source drift, and superseded historical drift.
4. Connect active completion-proof audit failures to terminal preflight without
   turning harmless historical drift into a global strict failure.
5. Provide a shorter direct-route command that records QA output, Evidence Set,
   completion-policy evaluation, and packet inputs without starting a Workflow.
