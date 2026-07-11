# 0150: Evidence-set completeness contract

- **Status:** Done locally; implemented and verified, not committed
- **Milestone:** v0.4.3 Evidence Completeness
- **Priority:** P0
- **Dependencies:** v0.4.2 local RC; approved `docs/plan-v0.4.3.md`
- **DB schema:** remain 8; stop for human approval if a migration is needed

## Problem

Hash-pinned Evidence proves what was selected, not that the selection is a
complete account of the target. LP dogfood selected passing reports while a
known 35.3% coordinate report and missing completion verdict remained outside
the Evidence row.

## Scope

- Define and schema-validate a deterministic `evidence-set/v1` artifact.
- Bind it to one target, an explicit work root, and a declared report manifest.
- Record included Evidence, required report kinds, known exclusions, and a
  completeness assessment.
- Provide read-only plan/inspect output before record mutation.
- Warn when a bundle excludes discovered related reports; reject terminal use
  only when target policy marks the report required or blocking.
- Package the schema and freeze canonical JSON/text fixtures.

## Invariants

- No arbitrary repository or parent-directory scan.
- Filesystem proximity alone never creates an authoritative relationship.
- Discovery order and finding order are deterministic.
- Existing Evidence rows remain immutable and usable.
- A rejected command leaves zero Evidence, link, or event traces.

## Non-scope

- Domain-specific verdict semantics.
- Test/Feature terminal mutations.
- Approval provenance.
- DB migration, hosted indexes, or LLM classification.

## Acceptance criteria

1. Schema, validator, package-data tests, and canonical fixtures exist.
2. The 35.3%-excluded fixture reports an incomplete required evidence set.
3. Optional unrelated sibling files do not block completeness.
4. Path escape, symlink escape, malformed JSON, missing manifest, and duplicate
   role cases fail closed with zero mutation traces.
5. JSON/text output is deterministic under reversed unordered SQLite selects.
