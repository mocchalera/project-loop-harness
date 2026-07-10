# 0140a: Skill / CLI contract parity

- **Status:** Approved v0.4.0 RC2 release blocker
- **Milestone:** v0.4.0 Integrity Gate
- **Priority:** P0
- **Estimated size:** S
- **Dependencies:** 0140
- **Parallel-safe with:** 0140b, 0140c

## Problem

Real-task dogfood found that the bundled `project-control-loop` Skill contains
copy-paste commands that the bundled CLI rejects. In particular, the direct
implementation example omits the required `--summary` argument for
`pcl feature status ... --status done`. The Skill also does not explain how a
direct route should produce reviewable Evidence and close a Goal without
inventing a Workflow Run.

This is a distribution contract failure: an agent can follow the shipped
instructions exactly and still hit a usage error or record weak terminal proof.

## Goal

Make the bundled Skill an executable contract for the v0.4.0 direct route:

1. `pcl start "<literal intent>"`;
2. Story draft and explicit approval or waiver;
3. Test plan linked to the Story;
4. hash-pinned Evidence creation;
5. Test pass and Feature done using a canonical Evidence ID;
6. target-bound completion packet creation;
7. Goal close using the completed packet, or an approved `V-XXXX` for a
   Workflow-backed route.

## Scope

- Update all three canonical Skill copies:
  - `skills/project-control-loop/SKILL.md`;
  - `src/pcl/templates/skills/project-control-loop/SKILL.md`;
  - `plugins/codex-project-loop/skills/project-control-loop/SKILL.md`.
- Add the missing `--summary` arguments.
- Explain that `--verification` accepts a Verification ID, not free text.
- Explain the compatibility boundary between legacy `--evidence` and canonical
  `--evidence-id`.
- Keep the three copies byte-identical.
- Add parser-level tests for the major command examples so future required-flag
  drift fails CI.

## Invariants

- No runtime, DB schema, dependency, hosted service, or automatic approval
  change belongs in this task.
- Project-local generated Skill copies are not patched directly.
- Entity-not-found after successful CLI parsing is acceptable in the contract
  test; argparse usage errors are not.

## Acceptance criteria

- Every direct-loop command includes all required arguments.
- The three canonical Skill copies have the same SHA-256.
- Distribution and fresh-init tests prove the packaged Skill is identical.
- Parser contract tests cover start, Story, Test, Evidence, Feature, finish,
  Goal closure, and Verification ID examples.
- Targeted tests and `ruff check` pass.
