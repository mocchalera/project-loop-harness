# Codex Project Loop Plugin

This folder packages Project Loop Harness instructions for Codex users.

The plugin bundles:

- the `project-control-loop` Skill;
- safe optional hooks metadata;
- UI metadata for Codex.

Important: the Python `pcl` CLI remains the runtime. This plugin does not install
the Python package, does not start an MCP server, and does not duplicate CLI
logic.

## Prerequisites

Install and verify `pcl` separately before using this plugin with a target
repository:

```bash
pipx install project-loop-harness
pcl --version
pcl --help
```

For unreleased changes, use a pinned GitHub tag or commit:

```bash
pipx install "git+https://github.com/mocchalera/project-loop-harness.git@<commit-or-tag>"
```

Then initialize the target repository:

```bash
cd target-project
pcl init
pcl doctor
```

## Plugin contents

```text
plugins/codex-project-loop/
├─ .codex-plugin/plugin.json
├─ hooks/hooks.json
├─ marketplace.example.json
├─ mcp.example.json
├─ package-files.json
└─ skills/project-control-loop/SKILL.md
```

`mcp.example.json` is intentionally not referenced by the plugin manifest.
The Python package provides `pcl-mcp`, but this plugin does not install the
package or enable MCP automatically.
`package-files.json` is the machine-readable inventory that tests use to keep
the package boundary deterministic.

## Expected user flow

```bash
pcl --help
pcl doctor
```

Then in Codex:

```text
Use the project-control-loop skill to run the next feature coverage step.
```

The Skill should guide Codex to use `pcl` commands such as:

```bash
pcl loop status
pcl loop run feature_coverage --goal G-0001
pcl prompt job J-0001
pcl agent command J-0001 --adapter manual
pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md
pcl render
```

## Local plugin testing

From this repository:

```bash
python -m pip install -e '.[dev]'
pytest tests/test_codex_plugin.py
```

Manual smoke test against a target repository:

```bash
cd target-project
pcl doctor
pcl next
```

Then use Codex's local plugin installation flow for this directory:

```text
plugins/codex-project-loop
```

After installation, ask Codex to use the `project-control-loop` Skill. The
plugin should not mutate files by itself; state changes must still go through
`pcl`.

## Safety notes

- Hooks are empty by default.
- No hook mutates files.
- No external service is called by the plugin.
- The plugin does not assume API keys.
- The plugin does not install or start `pcl-mcp`.
- The optional MCP example defaults to read-only tools.
