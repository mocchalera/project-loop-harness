# PyPI Publishing

Project Loop Harness publishes through PyPI Trusted Publishing, not long-lived
API tokens.

The release workflow is:

```text
.github/workflows/publish-pypi.yml
```

It builds the source distribution and wheel, runs `twine check`, and then uses
`pypa/gh-action-pypi-publish@release/v1` with GitHub OIDC. No `PYPI_TOKEN` or
`TEST_PYPI_TOKEN` secret is required.

## Trusted Publisher Setup

Create pending publishers before the first publish. A pending publisher does
not reserve the package name until the first successful publish.

### TestPyPI

Use TestPyPI first:

```text
Project name: project-loop-harness
Owner: mocchalera
Repository name: project-loop-harness
Workflow filename: publish-pypi.yml
Environment name: testpypi
```

Run the workflow manually:

```bash
gh workflow run publish-pypi.yml --repo mocchalera/project-loop-harness -f repository=testpypi
```

After it succeeds, install from TestPyPI in a scratch environment:

```bash
python -m venv /tmp/pcl-testpypi-smoke
/tmp/pcl-testpypi-smoke/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  project-loop-harness==0.1.9
/tmp/pcl-testpypi-smoke/bin/pcl --help
```

### PyPI

After TestPyPI is verified, create the real PyPI pending publisher:

```text
Project name: project-loop-harness
Owner: mocchalera
Repository name: project-loop-harness
Workflow filename: publish-pypi.yml
Environment name: pypi
```

The preferred production path is to publish a GitHub Release for a tag such as
`v0.1.9`. The workflow publishes to PyPI only when a release is published or
when manually dispatched with `repository=pypi`.

Manual production dispatch is available but should be used only after reviewing
the built version and confirming that the version has not already been uploaded:

```bash
gh workflow run publish-pypi.yml --repo mocchalera/project-loop-harness -f repository=pypi
```

## Release Checklist

Before publishing:

```bash
ruff check .
pytest
pcl validate --strict --json
pcl render --json
python -m build --sdist --wheel
python -m twine check dist/*
```

For local artifact smoke testing:

```bash
python -m venv /tmp/pcl-wheel-smoke
/tmp/pcl-wheel-smoke/bin/python -m pip install --no-index --find-links dist project-loop-harness==0.1.9
/tmp/pcl-wheel-smoke/bin/pcl init --target /tmp/pcl-wheel-demo
/tmp/pcl-wheel-smoke/bin/pcl validate --root /tmp/pcl-wheel-demo --strict
/tmp/pcl-wheel-smoke/bin/pcl render --root /tmp/pcl-wheel-demo --json
```
