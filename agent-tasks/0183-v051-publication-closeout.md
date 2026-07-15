# 0183: v0.5.1 publication closeout

- **Status:** In Progress; publication authorized by `ask_6e4c5b339398`
- **Milestone:** v0.5.1 Trace & Efficient Handoff
- **Priority:** P1
- **Size:** S
- **Dependency:** 0182 approved local RC and authorized publication

## Goal

After separately authorized publication, independently verify the immutable
v0.5.1 GitHub/PyPI chain and synchronize only factual release documentation.

## Scope

1. Verify tag, release commit, GitHub Release, release-triggered Actions run,
   and PyPI wheel/sdist metadata and hashes.
2. Install the public artifact in a clean environment and repeat init,
   Trace-context, resume, strict validation, and render smoke.
3. Record public artifact hashes, compatibility limits, and any observed
   packaging difference.
4. Synchronize release/task/roadmap status only after public facts agree.

## Invariants

- This task does not infer publication authority from an approved local RC.
- No launch post, provider run, telemetry, migration, or unrelated repair.
- Public verification is read-only; any release mutation follows its separately
  recorded authorization and release procedure.

## Acceptance

1. Tag, commit, Release, Actions, and PyPI resolve to the same v0.5.1 source.
2. Public artifact hashes match published metadata.
3. Clean public install passes the Trace/no-index smoke and strict validation.
4. Factual docs and task state are synchronized with reviewable evidence.

## Non-goals

- External-user study or adoption claim.
- Automatic announcement or broader distribution campaign.
