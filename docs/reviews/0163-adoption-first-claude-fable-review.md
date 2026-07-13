# 0163 Adoption-first milestone review

- Date: 2026-07-13
- Reviewer: Claude Fable through AGI Cockpit
- Cockpit task: `9638926d`
- Mode: read-only
- Reviewed state: uncommitted 0163 implementation diff
- Initial verdict: **APPROVE, conditional on R1**

## Findings

### Blocking

None.

### Required

1. README described `--force` broadly enough to imply that existing
   `AGENTS.md`, `CLAUDE.md`, and `.gitignore` content could be replaced. The
   implementation always uses append-once marked blocks for those files;
   `--force` replaces generated templates such as `pcl.yaml`, workflows, the
   bundled Skill, and dashboard files. README must state that exact boundary.

### Advisory

1. Replace the fixed 2099 authorization expiry with a value relative to the
   test runtime so the acceptance statement and implementation match literally.
2. Define what “documented” means in the stability policy and point to canonical
   contract documents or packaged schemas.
3. The visual golden-path demo remains intentionally deferred to the P1 launch
   packet, so 0163 completes the text path rather than the whole public launch.

## Independent verification

- Adoption/Profile targeted tests: 52 passed.
- Full suite: 960 passed, 1 skipped.
- Ruff: clean.
- Init coexistence claims were checked against `src/pcl/init_project.py` and
  existing initialization tests.
- Roadmap and human-gate consistency were checked across the canonical indexes,
  implementation/growth plans, Council adoption evidence, and README.

## Disposition

All three findings were applied:

- README now distinguishes append-once project instructions from replaceable
  generated templates.
- The authorization test computes expiry as current UTC plus one day while the
  expired-input regressions remain unchanged.
- The stability policy defines documented surfaces through canonical contract
  documents and packaged schemas.

After R1, the review states that the change is equivalent to an unconditional
**APPROVE**. Publication, provider execution, telemetry, default Council use,
and other external actions remain outside this milestone.

Claude Fable rechecked the applied diff in the same Cockpit task and confirmed:
`R1` resolved, `A1` resolved, `A2` resolved, no remaining required findings,
and final verdict **APPROVE (unconditional)**.
