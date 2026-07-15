# Post-v0.5.1 maintainability plan

- **Status:** Active; first Stage 2 family complete
- **Activated:** 2026-07-15
- **Decision source:** owner instruction to continue after verified v0.5.1 publication
- **Release label:** unassigned; completing a slice does not imply a new release

## Goal

Reduce maintainer risk in the two largest orchestration modules without changing
the observable CLI contract, while continuing to treat real project use as the
source of product-friction evidence.

## Exit conditions

1. Pure presentation helpers are isolated and directly characterized.
2. Selected read-only handlers can be extracted one family at a time with
   zero-mutation and output-parity evidence.
3. Mutating handlers remain in their current service and transaction boundaries
   until each lifecycle family has dedicated event, audit, and rejection tests.
4. Parser construction moves only after handler extraction stabilizes.
5. Every slice passes its affected tests, distribution/Skill tests, full Ruff
   and pytest, strict PCL validation, render, and `git diff --check`.
6. Dogfood observations remain factual and do not become adoption claims.

## Milestones

1. **0184 — Stage 1 presentation extraction (done).** Move state-free JSON/text
   formatting into a narrow module, retain compatibility imports, and freeze
   representative output with direct tests.
2. **Stage 2 read-only handler extraction (first family done).** 0185 extracts
   the bounded `pcl guide` family; keep parser definitions unchanged for later
   families.
3. **Stage 3 lifecycle handler extraction.** Move one mutating family at a time
   without moving transactions or event ownership.
4. **Stage 4 parser construction.** Split parser builders last while preserving
   the existing top-level entry point and complete help matrix.

0185 is complete. Later command families receive numbered task files only when
activated; this avoids reserving scope before dogfood and review show the next
safest boundary.

## Invariants

- No schema migration, dependency addition, hosted service, telemetry, provider
  execution, or external publication.
- Command names, parser behavior, output, JSON, errors, exit codes, events,
  transactions, gates, generated artifacts, and package entry points remain
  unchanged unless separately approved as feature work.
- External-user research remains useful Adoption evidence when participants
  become available, but it is not a blocker for maintainability work.
