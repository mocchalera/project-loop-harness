# Distribution Plan

For operator-facing installation, target-project setup, and first-prompt
templates, see [adoption-guide.md](adoption-guide.md). This file describes the
distribution components and readiness checks.

## Product components

```text
pcl CLI      = runtime
Skill        = agent instructions
Plugin       = Codex packaging wrapper
MCP server   = optional external bridge
Templates    = files installed into target projects
GitHub Action = optional CI integration
```

## Phase 1: CLI package

Ship as a Python package with a `pcl` console script.

```bash
pipx install project-loop-harness
cd target-project
pcl init
```

Before a package is published, use a pinned GitHub install instead:

```bash
python -m pip install "project-loop-harness @ git+https://github.com/mocchalera/project-loop-harness.git@<commit-or-tag>"
```

## Phase 2: Project template installer

`pcl init` writes:

- `pcl.yaml`;
- `.project-loop/`;
- `.agents/skills/project-control-loop/SKILL.md`;
- AGENTS.md block;
- CLAUDE.md block;
- `.gitignore` fragment.

## Phase 3: Codex plugin

Package skill, hooks, and MCP config under `plugins/codex-project-loop/`.

## Phase 4: MCP server

Expose safe read operations first:

- `get_status`;
- `list_features`;
- `list_defects`;
- `list_escalations`.

Run locally over stdio:

```bash
pcl-mcp --stdio --root target-project
```

`render_dashboard` is available only when local writes are explicitly approved:

```bash
pcl-mcp --stdio --root target-project --approval-mode local-render
```

The `render_dashboard` tool returns both generated artifact paths:

```json
{
  "dashboard": "target-project/.project-loop/dashboard/dashboard.html",
  "data_path": "target-project/.project-loop/dashboard/dashboard-data.json",
  "rendered": true
}
```

Add mutation tools later with approval gates.

## Phase 5: CI

Add GitHub Action for validation and dashboard freshness.

This repository ships a reusable composite action:

```text
.github/actions/project-loop-validate/action.yml
```

Example usage in a target repository:

```yaml
name: Project Loop Validate

on:
  pull_request:
  workflow_dispatch:

jobs:
  project-loop:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: owner/project-loop-harness/.github/actions/project-loop-validate@v0.1.1
        with:
          root: "."
          strict: "true"
          render: "true"
```

The action installs the Python runtime through its `install-command` input. For this repository's own CI, the workflow passes `python -m pip install -e '.[dev]'`. A published consumer should use the default `python -m pip install project-loop-harness` or pin an approved version.

## Distribution smoke

Editable installs are not enough to prove distribution readiness. Run:

```bash
python -m pip wheel . --no-deps --no-build-isolation -w /tmp/pcl-wheelhouse
python -m venv /tmp/pcl-wheel-venv
/tmp/pcl-wheel-venv/bin/python -m pip install --no-deps /tmp/pcl-wheelhouse/project_loop_harness-*.whl
/tmp/pcl-wheel-venv/bin/pcl --help
/tmp/pcl-wheel-venv/bin/pcl-mcp --help
```

Then initialize a scratch project with the installed `pcl` and verify:

```bash
/tmp/pcl-wheel-venv/bin/pcl init --target /tmp/pcl-dist-demo
/tmp/pcl-wheel-venv/bin/pcl --root /tmp/pcl-dist-demo validate --strict
/tmp/pcl-wheel-venv/bin/pcl --root /tmp/pcl-dist-demo render
/tmp/pcl-wheel-venv/bin/pcl --root /tmp/pcl-dist-demo next --json
```

The same path is covered by `pytest tests/test_distribution.py`.
