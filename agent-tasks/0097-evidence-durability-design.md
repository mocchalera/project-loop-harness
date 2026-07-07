# Task 0097: Evidence Durability Modes — Design Only (v0.2.3, P1)

Origin: GPT-5.5-pro v0.2.2 review agenda, blind spot A ("hash-pin is
not durability"). **This task produces a design document only — no
code, no schema change, no CLI change.** Authored by the
orchestrator (not dispatched to an implementation worker) because it
is a judgment/trade-off document requiring approval, not a build.

## Problem

v0.2.2 adhoc evidence records member path + size + sha256 but never
copies the file. This is honest ("existed with this content at record
time") but weak for later review: cleanup deletes
`work/reports/pytest-out.txt`, CI artifacts expire, screenshots live
outside the repo, overwritten files leave only a drift warning.

A naive `--copy` does not fix this either, because
`.project-loop/evidence/` is **gitignored** (`.gitignore:20`): a copy
survives local cleanup but still does not travel to another machine
or reviewer. Durability design is inseparable from the git/versioning
boundary of `.project-loop`, so the boundary question must be settled
before any implementation.

## Deliverable

`docs/evidence-durability-design.md` covering at minimum:

1. Modes: `reference` (today, stays default) vs explicit `--copy`
   (member files copied under `.project-loop/evidence/adhoc-files/`)
   vs a possible `--snapshot`/export-bundle variant; what each does
   and does not promise.
2. Manifest accounting: `storage_mode: reference | copied` per
   member or per manifest; interaction with drift detection (a copy
   can also drift or be deleted).
3. The gitignore boundary problem: options (keep evidence local-only;
   carve out a committed evidence subdirectory; an explicit
   `pcl evidence export` bundle for hand-off) with a recommendation.
4. Interaction with 0096 guards: copying must never weaken them —
   sensitive-shaped members and outside-root members and copy mode
   compose (e.g. copying an outside-root file pulls it inside the
   boundary: is that a feature or a loophole? decide and say why).
5. Size discipline: soft cap for copied members, `large_evidence_member`
   warning, relation to strict-validate hash cost (review blind spot
   F stays backlog; the design should not preclude it).
6. Truthfulness boundary: PLH never claims copied content is correct,
   only that it was copied from the named path at record time.
7. Decision points listed explicitly for approval; no default-copy —
   copying stays opt-in per invocation.

## Definition of done

- Design doc committed to `main`, marked as awaiting approval.
- Open decisions presented for approval before any implementation
  task is cut (implementation would be a v0.2.4+ task).
