# Task 0084: `source_commands` Honesty (P0)

## Goal

Context packs currently list `pcl impact --diff --json` in
`source_commands` when `--include-code-context` is passed
(`src/pcl/context.py`, both `pack_context_for_job` and
`pack_context_for_task`). But pack generation never runs that command:
it only reads the latest existing `context_receipt` evidence. Worse,
`pcl impact --diff` is not a read-only re-fetch — running it CREATES a
new receipt (new evidence row + artifact). For a tool whose brand is
honest provenance, a pack asserting a mutating command it did not run
is a false attestation, not a vocabulary nuance.

Fix the field to be honest, and give refresh guidance its own clearly
named home.

## Design constraints (agreed, do not relitigate)

- `source_commands` is DEFINED as: read-only commands a reader can run
  to re-fetch the same inputs this pack was built from. They must not
  create evidence, artifacts, or any state change. Document this
  definition.
- `suggested_refresh_commands` is DEFINED as: commands that would
  REGENERATE the underlying artifacts (they may create new evidence,
  e.g. a fresh context receipt). Document this definition and the
  distinction.
- Removing the false `pcl impact --diff --json` entry from
  `source_commands` is a deliberate honesty fix within
  `context-pack/v1` (consumers must not depend on the presence of a
  specific list element); call this out in the docs changelog section
  for the release notes.
- No schema migration, no new runtime dependency.

## Scope

### 1. Remove the false entry

- Delete `pcl impact --diff --json` from `source_commands` in both
  job and task pack builders. The remaining entries (`pcl jobs read`,
  `pcl prompt job`, `pcl task read`, `pcl task list`, `pcl validate`)
  are read-only re-fetch commands and stay.

### 2. Add `suggested_refresh_commands`

- New top-level pack field, present only when
  `--include-code-context` was requested.
- Value is staleness-aware and must agree with the logic already used
  by `_next_recommended_command` in
  `src/pcl/code_context/summary.py` (extract a shared helper rather
  than duplicating the decision):
  - summary has `staleness_warnings` → `["pcl index build --json",
    "pcl impact --diff --json"]`
  - summary status is `missing_receipt` or `unavailable` →
    `["pcl index build --json", "pcl impact --diff --json"]`
  - otherwise → `["pcl impact --diff --json"]`
- `pcl receipt show`'s "Next Recommended Command" rendering keeps its
  current output (it may reuse the shared helper).

### 3. Documentation

- `docs/context-pack.md`: document both field definitions
  (read-only re-fetch vs artifact-regenerating suggestion), state
  explicitly that pack generation never executes `pcl impact`, and
  note the removal of the old misleading entry.

## Acceptance Criteria

- Packs built with `--include-code-context` contain NO `pcl impact`
  entry in `source_commands` and DO contain
  `suggested_refresh_commands`.
- Packs built without the flag contain neither the impact entry nor
  the `suggested_refresh_commands` field (field absent, not null).
- `suggested_refresh_commands` reflects staleness / missing-receipt /
  fresh cases (one test per branch), and matches what
  `pcl receipt show` recommends for the same receipt state.
- Every command listed in `source_commands` across all pack kinds is
  read-only (assert against an explicit allowlist in a test, so a
  future mutating entry fails loudly).
- `ruff check .` passes; full `python3 -m pytest` passes; `pcl init`
  smoke against a temp dir passes.

## Do Not

- Do not rename or repurpose the existing `next_actions` concept in
  the receipt-show rendering; `suggested_refresh_commands` is a pack
  field, not a receipt field.
- Do not execute `pcl impact` (or any artifact-creating command)
  during pack generation.
- Do not add `safe_to_continue` or any go/no-go field.
- Do not use raw SQL to mutate `.project-loop/project.db`.
- Do not add hosted services, telemetry, or new runtime dependencies.
