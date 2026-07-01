# Task 0060: PyPI Trusted Publishing

## Goal

Prepare Project Loop Harness for PyPI/TestPyPI publishing through GitHub Actions
Trusted Publishing.

The package should publish through short-lived OIDC credentials instead of
long-lived PyPI API tokens.

## Scope

- Add `.github/workflows/publish-pypi.yml`.
- Build sdist and wheel in CI.
- Run `twine check` before upload.
- Publish to TestPyPI through manual workflow dispatch.
- Publish to PyPI through GitHub Release publication or explicit manual
  dispatch.
- Use separate GitHub environments named `testpypi` and `pypi`.
- Document pending publisher setup fields and release checklist.

## Acceptance Criteria

- The workflow contains no PyPI token secrets.
- The publish jobs use job-level `id-token: write`.
- TestPyPI uses `repository-url: https://test.pypi.org/legacy/`.
- Production PyPI upload does not run on normal pushes.
- Documentation names the exact pending publisher fields:
  `project-loop-harness`, `mocchalera`, `project-loop-harness`,
  `publish-pypi.yml`, and environment `testpypi` or `pypi`.
- Local package build, `twine check`, wheel install smoke, tests, strict
  validation, and render pass before publish.

## Do Not

- Do not add PyPI API tokens to repository secrets.
- Do not publish from pull requests or normal pushes.
- Do not make PyPI publishing mutate project-loop SQLite state.
- Do not add runtime dependencies for publishing.
