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
pcl --version
cd target-project
pcl init
```

For CI or a project-specific virtual environment, install the same published
package with pip:

```bash
python -m pip install project-loop-harness
```

Operators can explicitly check for newer PyPI releases without upgrading:

```bash
pcl update check
pcl doctor --check-updates
pcl update command
```

The checker reads `https://pypi.org/pypi/project-loop-harness/json`, stores a
24-hour cache under the user's cache directory, and only reports the result. It
does not auto-upgrade the package, write telemetry, or contact any service
unless the operator runs the update-check command. `PCL_NO_VERSION_CHECK=1`
disables the check.

For unreleased commits or internal dogfooding, use a pinned Git install instead:

```bash
python -m pip install "project-loop-harness @ git+https://github.com/mocchalera/project-loop-harness.git@<commit-or-tag>"
```

Publishing is handled through GitHub Actions Trusted Publishing, not long-lived
PyPI API tokens. See [pypi-publishing.md](pypi-publishing.md) for the exact
TestPyPI/PyPI pending publisher fields and release checklist.

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

The `render_dashboard` tool renders both dashboard artifacts, but returns only
machine-oriented metadata. The generated HTML is a human-only view and is not
returned as agent context:

```json
{
  "data_path": "target-project/.project-loop/dashboard/dashboard-data.json",
  "machine_context": "Use data_path or read-only MCP tools for state. dashboard.html is human-only and intentionally not returned.",
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
      - uses: owner/project-loop-harness/.github/actions/project-loop-validate@v0.1.9
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

## PyPI Release Workflow

The repository ships:

```text
.github/workflows/publish-pypi.yml
```

The workflow:

- runs only on GitHub Release publication or manual dispatch;
- builds both sdist and wheel;
- runs `twine check`;
- publishes to TestPyPI with `repository=testpypi`;
- publishes to PyPI on a published GitHub Release or manual
  `repository=pypi` dispatch;
- uses OIDC Trusted Publishing through job-level `id-token: write`;
- does not require `PYPI_TOKEN` or `TEST_PYPI_TOKEN` secrets.
