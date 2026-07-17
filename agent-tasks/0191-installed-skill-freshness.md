# 0191: Installed Skill Freshness and Workflow Discipline

- **Status:** Active
- **Milestone:** v0.5.2 Adoption Proof
- **Priority:** P0
- **Size:** M
- **Dependency:** 0189 adoption proof; Cockpit task `9649a8d2` field review
- **DB schema:** remains 8

## Problem

An initialized adopter project keeps its original
`.agents/skills/project-control-loop/SKILL.md` forever. A newer `pcl` runtime
therefore cannot tell the operator that the installed Skill still recommends
legacy inline evidence, omits Story linkage, or lacks current-intent routing.
Normal `pcl init --dry-run` reports the existing Skill as an unconditional
skip, so runtime improvements do not reach the agent instructions.

The same field review found two repeatable operating failures: `pcl next`
pointed to an unrelated older Feature, and mutable evidence report paths were
rewritten until ten registered hashes drifted. It also showed the intended
positive pattern: waive a user-corrected Test and add its replacement rather
than rewriting acceptance history.

## Scope

1. Detect installed Skill bytes that differ from the bundled Skill.
2. Add explicit `pcl init --refresh-skill` preview/apply behavior.
3. Preserve replaced Skill bytes in a SHA-256-addressed local backup.
4. Append one audit event when an initialized project changes Skill bytes.
5. Keep config, workflow templates, dashboard, and project state untouched.
6. Add current-intent, write-once evidence, and corrected-acceptance rules to
   every distributed Skill copy.

## Invariants

- No schema migration, dependency addition, network access, or publication.
- Normal `pcl init` remains non-overwriting.
- `--refresh-skill` is mutually exclusive with `--force` and
  `--repair-config`.
- Dry-run is deterministic and read-only.
- A second refresh against current bytes is idempotent.
- Replaced bytes remain recoverable even when the installed Skill had local
  customization.

## Acceptance

1. `pcl doctor --json` emits typed `installation_skill_drift` guidance with a
   dry-run command and an apply command.
2. Refresh dry-run identifies only the Skill and its hash-addressed backup as
   writes.
3. Apply updates the Skill, preserves old bytes, appends
   `project_skill_refreshed`, and leaves unrelated files byte-identical.
4. A second apply changes no files and appends no event.
5. All canonical, template, plugin, and repo-local Skill copies remain
   byte-identical and pass Skill validation.
6. Targeted tests, full pytest, fresh init smoke, strict validation, render,
   and diff checks pass.
