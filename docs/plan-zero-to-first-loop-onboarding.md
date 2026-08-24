# Zero-to-First-Loop onboarding bootstrap plan

- **Status:** Active — design-gate/bootstrap work only
- **Priority:** P0
- **Origin:** GitHub Issue #6
- **Authorized scope:** establish the repository-local authority and produce the
  first-use product decision; runtime and packaged-instruction implementation
  remain blocked until that decision is accepted
- **External adoption claim:** none

## 1. Purpose

Project Loop Harness cannot evaluate external adoption while its maintainer
cannot confidently explain one canonical sequence for introducing PCL into an
existing repository and assigning the first real task to a coding agent.

This plan establishes the minimum authority, evidence, and work order needed to
begin Issue #6 without pretending that the final onboarding flow is already
known.

The bootstrap must answer one product question before implementation:

> What is the single primary path from an existing repository and an assigned
> task to the first reviewable PCL result, and which actions belong to the human
> versus the coding agent?

## 2. Authority and work boundary

- GitHub Issue #6 is the contributor-facing work request.
- This document is the accepted repository-local anchor for its design-gate
  phase.
- Existing PCL state, accepted specs, and Evidence remain lifecycle authority.
- `AGENTS.md` governs agents developing PCL itself.
- `src/pcl/templates/project/AGENTS.block.md`,
  `src/pcl/templates/project/CLAUDE.block.md`, bundled Skills, and generated
  project files are product outputs. They are not changed to imply a final
  first-use contract until the decision gate is accepted.
- The five-participant study in Issue #2 remains closed without adoption
  evidence. Maintainer dogfood under Issue #6 cannot replace it.

The bootstrap phase may inspect, compare, document, test existing behavior, and
prepare a decision proposal. It may not silently choose a product identity or
change public runtime behavior.

## 3. Starting defects to resolve

The design gate begins from these confirmed project-level problems:

1. The previous root `AGENTS.md` told agents to execute `agent-tasks/` in numeric
   order, even though GitHub Issues now provide the contributor-facing current
   work view and accepted anchors/PCL state provide authority.
2. The root development instructions, generated `AGENTS.md` block, generated
   `CLAUDE.md` block, README, guides, and bundled Skills do not yet prove one
   identical first-loop sequence.
3. Current instructions emphasize internal entities and safety rules but do not
   reliably answer what a human should do immediately after initialization or
   what an agent should do immediately after receiving a GitHub Issue or
   free-form task.
4. The repository contains two plausible entry models that must not remain
   equally primary:
   - full loop: intent → bounded work → checks/Evidence → completion → handoff;
   - completion verification: implemented change → `pcl verify` → verdict.
5. Human-owned and agent-owned operations are not frozen as one testable
   contract across all shipped surfaces.

## 4. Bootstrap work order

### Phase A — Characterize the shipped baseline

Inventory exact behavior and wording at one frozen commit/candidate for:

- `pcl init --dry-run --json` and `pcl init`;
- the immediate post-init output and generated files;
- `pcl start`, `pcl next --json`, `pcl resume`, `pcl finish`, `pcl verify`,
  `pcl close`, and the final review surfaces that actually exist;
- `README.md`, `docs/adoption-guide.md`, `docs/golden-path.md`, command and
  recovery guides;
- root `AGENTS.md` and `CLAUDE.md`;
- generated `AGENTS.block.md` and `CLAUDE.block.md`;
- bundled Codex, Claude, and generic agent instructions;
- source checkout, installed wheel, and installed sdist contents.

Record facts, contradictions, missing steps, nonexistent commands/flags, and
places where maintainer memory is required. Do not normalize discrepancies by
interpretation.

### Phase B — Produce one decision proposal

Prepare one explicit decision record that freezes:

- the primary first-use promise;
- whether the canonical path begins before implementation or at completion
  verification;
- the relationship of the non-primary path to advanced usage;
- the minimum human actions from install through final review;
- the routine operations owned by the coding agent;
- how a GitHub Issue and a free-form task become PCL work without duplicating
  authority;
- which Goal/Task/Feature/Story/Test concepts remain hidden in the first loop;
- the exact conditions that return control to the human;
- the final review surface and factual completion vocabulary;
- recovery behavior for an interrupted or ambiguous first attempt.

The proposal must contain one canonical sequence, not a menu of equally
recommended alternatives.

### Phase C — Human decision gate

Implementation remains blocked until a human accepts, modifies, or rejects the
proposal. The decision record must state the accepted scope and explicitly list
rejected alternatives.

No agent may infer acceptance from silence, Issue state, a passing test, or the
existence of this plan.

### Phase D — Split implementation

After acceptance, create independently reviewable task specs for at least:

1. canonical documentation and two copyable task prompts;
2. initialization/immediate handoff behavior;
3. human/agent ownership contract in generated instructions;
4. README/guide/Skill/source/wheel/sdist parity tests;
5. Python and Node/TypeScript maintainer-blind dogfood;
6. remediation and rerun against the same frozen protocol.

Do not create one broad implementation task that mixes the product decision,
CLI behavior, all documentation, packaging, and dogfood.

## 5. Bootstrap acceptance criteria

The design-gate phase is ready for human decision only when:

- [ ] root `AGENTS.md` no longer treats numeric `agent-tasks/` order as the
      automatic work queue;
- [ ] Issue #6 maps to this repository-local anchor in
      `scripts/github-issue-map.json`;
- [ ] the exact candidate/commit under characterization is recorded;
- [ ] every first-use surface listed in Phase A has an observed status;
- [ ] actual CLI behavior and documentation claims are separated;
- [ ] the decision proposal contains one complete canonical sequence;
- [ ] human-owned and agent-owned actions are explicit;
- [ ] GitHub Issue/reference/state authority boundaries are explicit;
- [ ] no generated template or bundled Skill is presented as implementing an
      unaccepted onboarding decision;
- [ ] remaining unknowns and external-adoption limits are stated honestly;
- [ ] implementation tasks are not started before the human decision.

A contradiction or an inconvenient baseline result is valid evidence. Do not
weaken the gate to make the proposal appear ready.

## 6. Verification for this bootstrap change

At minimum run:

```bash
git diff --check
PYTHONPATH=src python scripts/render_github_backlog.py --root . --format json
pytest tests/test_github_backlog_projection.py
```

If the repository's current standard gate requires additional commands, run
those as well and record the exact commit and result. This bootstrap does not
claim runtime correctness from documentation-only review.

## 7. Non-goals

- Selecting the final onboarding flow inside this bootstrap plan.
- Adding a new CLI command before evaluating whether existing output can be
  simplified.
- Rewriting generated `AGENTS.md`/`CLAUDE.md` blocks before the decision gate.
- Reopening or simulating the external five-participant cohort.
- Claiming voluntary reuse or external adoption from maintainer dogfood.
- Adding hosted coordination, telemetry, automatic GitHub mutation, or a new
  broad state machine.
- Solving unrelated recovery or orchestration work without direct evidence that
  it blocks the first loop.
