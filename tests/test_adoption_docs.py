from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_readme_leads_with_short_value_and_agent_owned_routine_flow() -> None:
    readme = _read("README.md")
    readme_words = " ".join(readme.split())

    assert readme.index("## Understand it in 30 seconds") < readme.index(
        "## Get first value in five minutes"
    )
    assert readme.index("## Get first value in five minutes") < readme.index(
        "## Install and inspect in more detail"
    )
    assert "Do not ask me to run routine pcl commands" in readme
    assert "pcl start → implementation → finish → close" in readme
    assert "it does not replace existing project-instruction content" in readme_words
    assert "[Alpha Stability Policy](docs/stability-policy.md)" in readme


def test_adoption_guide_freezes_inspect_first_coexistence_boundary() -> None:
    guide = _read("docs/adoption-guide.md")

    assert "pcl init --dry-run --json" in guide
    assert "existing `AGENTS.md`, `CLAUDE.md`, and `.gitignore` content is retained" in guide
    assert "an existing `pcl.yaml` is preserved" in guide
    assert "Do not use `pcl init --force` merely to adopt" in guide
    assert "agent runs routine `pcl` commands" in guide


def test_stability_policy_names_protected_and_internal_surfaces() -> None:
    policy = _read("docs/stability-policy.md")
    policy_words = " ".join(policy.split())

    for protected in (
        "versioned JSON artifacts",
        "typed JSON error `code` values",
        "ordered forward migrations",
        "claims-not-facts boundary",
    ):
        assert protected in policy
    for internal in (
        "generated dashboard HTML markup and CSS",
        "internal Python modules",
        "physical SQLite table layout is internal",
    ):
        assert internal in policy
    assert "canonical contract document linked from the README" in policy_words
    assert "planning drafts" in policy_words
