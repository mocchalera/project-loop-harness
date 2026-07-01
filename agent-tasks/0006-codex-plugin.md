# Task 0006: Codex Plugin Packaging

## Goal

Make the `plugins/codex-project-loop/` scaffold installable and useful for Codex users.

## Read first

- `plugins/codex-project-loop/README.md`
- `plugins/codex-project-loop/.codex-plugin/plugin.json`
- `skills/project-control-loop/SKILL.md`
- `docs/distribution.md`

## Scope

- Verify plugin manifest shape.
- Keep Skill content in sync with root Skill.
- Add hooks only if they are safe and optional.
- Add marketplace example.
- Document installation and testing flow.

## Acceptance criteria

A Codex user can understand how to install the plugin and use the Skill with a target repository that already has `pcl` installed.

## Do not

- Do not assume plugin installation installs the Python CLI automatically unless verified.
- Do not add hooks that mutate files without explicit user action.
