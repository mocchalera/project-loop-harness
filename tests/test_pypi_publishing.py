from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-pypi.yml"
DOC = ROOT / "docs" / "pypi-publishing.md"


def test_pypi_publish_workflow_uses_trusted_publishing_without_tokens() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "pypa/gh-action-pypi-publish@release/v1" in text
    assert "id-token: write" in text
    assert "environment:\n      name: testpypi" in text
    assert "environment:\n      name: pypi" in text
    assert "repository-url: https://test.pypi.org/legacy/" in text
    assert "python -m build --sdist --wheel" in text
    assert "python -m twine check dist/*" in text
    assert "secrets.PYPI" not in text
    assert "PYPI_TOKEN" not in text
    assert "TEST_PYPI_TOKEN" not in text


def test_pypi_publish_workflow_does_not_publish_on_normal_pushes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" not in text
    assert "push:" not in text
    assert "types: [published]" in text
    assert "workflow_dispatch:" in text
    assert "inputs.repository == 'testpypi'" in text
    assert "inputs.repository == 'pypi'" in text


def test_pypi_publishing_docs_include_pending_publisher_fields() -> None:
    text = DOC.read_text(encoding="utf-8")

    for expected in [
        "Project name: project-loop-harness",
        "Owner: mocchalera",
        "Repository name: project-loop-harness",
        "Workflow filename: publish-pypi.yml",
        "Environment name: testpypi",
        "Environment name: pypi",
        "gh workflow run publish-pypi.yml",
    ]:
        assert expected in text
