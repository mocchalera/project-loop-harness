# LP production cross-skill dogfood review

**Source:** Cockpit task `cb004add` (`kikulab-design`)
**Observed:** 2026-07-11
**Scope:** read-only review of the completed LP workflow and its final
third-party assessment. This document does not modify or close the Cockpit
task.

## Result

The LP implementation was a strong prototype, but the two skills reported
different meanings of completion:

- seven sections and four clean generated photo assets were delivered;
- asset, manifest, responsive (320–1728 px), desktop/mobile intent, and page
  flow checks passed;
- strict mockup-coordinate matching passed only 6 of 17 checks (35.3%);
- the mockup workflow therefore classified the result as a high-quality
  prototype, not a complete mockup match;
- Project Loop nevertheless allowed the linked Test Case and Feature to reach
  `passing`, and `pcl next` could report idle.

The third-party review scored the overall result 72/100, with static visual
quality 82, web implementation 66, production readiness 58, Project Loop skill
design 80, and actual Project Loop operational alignment 62. These scores are
review observations, not measurements produced by Project Loop Harness.

## What worked

1. Project Loop detected the absence of state in the clean worktree and used
   the inspect-first initialization path.
2. It required Story/Test relationships and durable, hash-pinned Evidence for
   terminal mutations.
3. Strict validation passed and copied Evidence remained reviewable.
4. The agent did not falsely call the mockup result complete; the 35.3% result
   remained visible in its narrative handoff.

## Findings

### P0 — Positive-evidence selection can hide known negative evidence

The recorded Evidence selected passing visual, responsive, and page-flow
reports, but did not bind the 35.3% coordinate report, incomplete typography,
or a required completion verdict. A hash-pinned artifact is durable, but is not
automatically a complete representation of the target's evidence.

### P0 — PCL passing and domain completion are not bound

Project Loop knew that the referenced positive checks passed, but had no
generic contract for an external skill's `prototype` versus `complete` verdict.
PCL terminal status could therefore overstate the domain result.

### P1 — Unfinished passing work can route to idle

A Feature in `passing` is not a Feature in `done`. When the domain completion
verdict is missing or the Feature still needs an explicit terminal decision,
`pcl next` must expose that action rather than return neutral idle.

### P1 — Approval authority is underspecified

An agent's self-review, a tool-generated verdict, and explicit human approval
must not be presented as equivalent authority. Approval receipts need factual
actor/provenance fields, while existing human gates remain human gated.

### P1 — Skill documentation can encourage a weaker evidence path

Examples that use raw `--evidence` text beside `--evidence-id` obscure the
trust difference. `--evidence-id` should be the canonical terminal-proof path;
raw text remains a compatibility claim, not equivalent reviewable proof.

### P2 — Story linkage should be caught at planning time

Under enforced lifecycle policy, planning a Test Case without a Story should
warn or fail before the terminal transition. Existing projects can retain an
advisory compatibility path during migration.

## Product boundary

The core must not hard-code `mockup-to-code`, web design, DOM rectangles, or a
35.3% threshold. It should provide a deterministic completion-policy adapter
that evaluates declared JSON artifacts and predicates from any collaborating
tool. Domain-specific generation improvements remain owned by that tool:

- a formal Motion Phase;
- automatic crop-pair generation;
- detail-inventory extraction and omission warnings;
- early prototype-ceiling disclosure when independent review is unavailable;
- baseline-cluster visual line counting.

Project Loop only owns whether these declared external results are complete,
present, consistently linked, and honestly represented in lifecycle state.

## Disposition

All Project Loop findings are incorporated into `docs/plan-v0.4.3.md` and repo
tasks 0150–0153. The mockup-specific items above are external dependencies and
are not silently absorbed into the PCL core backlog.
