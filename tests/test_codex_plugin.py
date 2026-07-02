from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-project-loop"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _plugin_files() -> list[str]:
    return sorted(
        path.relative_to(PLUGIN).as_posix() for path in PLUGIN.rglob("*") if path.is_file()
    )


def _assert_plugin_relative_file(path_text: str) -> None:
    path = PurePosixPath(path_text)
    resolved = (PLUGIN / path_text).resolve()

    assert path_text
    assert str(path) == path_text
    assert not path.is_absolute()
    assert ".." not in path.parts
    assert resolved.is_relative_to(PLUGIN.resolve())
    assert resolved.is_file()


def test_codex_plugin_package_inventory_matches_files() -> None:
    inventory = _json(PLUGIN / "package-files.json")

    assert set(inventory) == {"contract_version", "description", "files"}
    assert inventory["contract_version"] == "codex-plugin-package-files/v1"
    assert "Codex Project Loop plugin package" in inventory["description"]

    files = inventory["files"]
    assert files == sorted(files)
    assert len(files) == len(set(files))
    assert files == _plugin_files()

    for path_text in files:
        _assert_plugin_relative_file(path_text)


def test_codex_plugin_manifest_shape() -> None:
    manifest = _json(PLUGIN / ".codex-plugin" / "plugin.json")

    assert manifest["name"] == "project-loop-harness"
    assert manifest["version"] == "0.1.6"
    assert manifest["license"] == "MIT"
    assert manifest["skills"] == "./skills/"
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert "mcpServers" not in manifest

    interface = manifest["interface"]
    assert interface["displayName"] == "Project Loop Harness"
    assert interface["category"] == "Productivity"
    assert interface["capabilities"] == ["Read", "Write"]
    assert "pcl remains the runtime" in interface["longDescription"]

    assert (PLUGIN / manifest["skills"]).resolve().is_dir()
    assert (PLUGIN / manifest["hooks"]).resolve().is_file()


def test_codex_plugin_manifest_paths_stay_in_package_inventory() -> None:
    manifest = _json(PLUGIN / ".codex-plugin" / "plugin.json")
    inventory = _json(PLUGIN / "package-files.json")
    files = set(inventory["files"])

    skills_path = (PLUGIN / manifest["skills"]).resolve()
    hooks_path = (PLUGIN / manifest["hooks"]).resolve()

    assert skills_path.is_relative_to(PLUGIN.resolve())
    assert hooks_path.is_relative_to(PLUGIN.resolve())
    assert manifest["hooks"].removeprefix("./") in files
    assert any(path.startswith("skills/") for path in files)


def test_project_control_loop_skill_is_synced_across_packages() -> None:
    root_skill = (ROOT / "skills" / "project-control-loop" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    expected_paths = [
        ROOT / "src" / "pcl" / "templates" / "skills" / "project-control-loop" / "SKILL.md",
        PLUGIN / "skills" / "project-control-loop" / "SKILL.md",
        ROOT / ".agents" / "skills" / "project-control-loop" / "SKILL.md",
    ]

    for path in expected_paths:
        assert path.read_text(encoding="utf-8") == root_skill

    assert "pcl prompt job J-0001" in root_skill
    assert "pcl ingest-agent-run .project-loop/evidence/agent-runs/J-0001/output.md" in root_skill


def test_codex_plugin_hooks_are_safe_and_optional() -> None:
    hooks = _json(PLUGIN / "hooks" / "hooks.json")

    assert hooks == {"hooks": []}


def test_codex_plugin_marketplace_example_documents_runtime_boundary() -> None:
    marketplace = _json(PLUGIN / "marketplace.example.json")

    assert marketplace["name"] == "project-loop-harness"
    assert marketplace["requires"]["pythonPackage"] == "project-loop-harness>=0.1.6"
    assert marketplace["requires"]["targetProjectInitialized"] is True
    assert "the Python pcl CLI" in marketplace["doesNotInstall"]
    assert "pcl --help" in marketplace["installTest"]
    assert marketplace["entrypoint"]["skill"] == "project-control-loop"


def test_mcp_config_is_example_only_until_mcp_task() -> None:
    mcp_example = _json(PLUGIN / "mcp.example.json")

    assert mcp_example["status"] == "example-only"
    assert mcp_example["mcpServers"]["project-loop-harness"]["command"] == "pcl-mcp"
    assert not (PLUGIN / ".mcp.json").exists()
