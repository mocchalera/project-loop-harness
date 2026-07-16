# 0189: v0.5.2 Adoption Proof

- **Status:** Active
- **Milestone:** v0.5.2 Adoption Proof
- **Priority:** P0
- **Size:** M
- **Dependency:** v0.5.1 public verification; 0184-0188 maintainability baseline
- **DB schema:** remains 8

## Goal

Reduce the path from installing Project Loop Harness to the first verified
completion, then measure that path with external users instead of treating
publication or internal dogfood as adoption.

## Scope

1. Make inspect-first initialization config-ready for common Python and Node
   repositories without executing project code or adopting unsafe commands.
2. Reduce the public README to one outcome, one quickstart, one operator mental
   model, and curated links to advanced material.
3. Put the existing reproducible 3-minute demo in the first public screenful.
4. Freeze a privacy-preserving five-person observation protocol across at least
   three real repository types.
5. Fix only the top observed activation blockers before release preparation.

## Invariants

- No schema migration, dependency addition, telemetry, hosted service, provider
  execution, automatic external write, or publication.
- `pcl init --dry-run` stays read-only and deterministic.
- Existing `pcl.yaml` and project instructions remain preserved by default.
- Project configuration files are read as data and never executed for detection.
- Clone, download, and CI counts are not presented as user adoption.

## Acceptance

1. Python and Node fixtures receive a real project name, safe checks, and
   explicit disabled values for unknown commands; unsafe candidates stay off.
2. Representative initialized projects have no placeholder, empty-command, or
   missing-finish-check doctor findings when a safe check is detected.
3. README stays at or below 200 lines and links the demo and cohort contract.
4. The cohort protocol records install-to-health, first verified completion,
   interventions, safety violations, and seven-day reuse.
5. Targeted tests, full Ruff, full pytest, fresh-project smoke, strict PCL
   validation, render, and diff check pass.

## Completion evidence

- `docs/evidence/0189-v052-adoption-proof.md`
- `docs/adoption-proof-v0.5.2.md`
