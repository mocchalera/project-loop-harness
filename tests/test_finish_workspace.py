from __future__ import annotations

import os
from pathlib import Path
import subprocess

from pcl.finish_workspace import isolated_finish_workspace
from pcl.verification_manifest import collect_verification_input_manifest


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "pcl-test@example.invalid")
    _git(tmp_path, "config", "user.name", "PCL Test")
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("dirty\n", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to("source.txt")
    _git(tmp_path, "add", ".gitignore", "source.txt", "linked.txt")
    _git(tmp_path, "commit", "-qm", "fixture")
    (tmp_path / "source.txt").write_text("working tree\n", encoding="utf-8")
    os.chmod(tmp_path / "source.txt", 0o755)
    (tmp_path / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    return tmp_path


def test_isolated_workspace_materializes_dirty_inputs_without_shared_git_metadata(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    manifest = collect_verification_input_manifest(root)
    workspace_path: Path | None = None

    with isolated_finish_workspace(
        root,
        input_manifest=manifest,
        commands=[],
    ) as workspace:
        workspace_path = workspace["root"]
        assert (workspace_path / "source.txt").read_text(encoding="utf-8") == (
            "working tree\n"
        )
        assert (workspace_path / "source.txt").stat().st_mode & 0o777 == 0o755
        assert os.readlink(workspace_path / "linked.txt") == "source.txt"
        assert (workspace_path / "untracked.txt").read_text(encoding="utf-8") == (
            "untracked\n"
        )
        assert workspace["public"] == {
            "kind": "independent_git_copy",
            "temporary": True,
            "git_metadata_shared": False,
            "input_manifest_sha256": manifest["manifest_sha256"],
            "copied_dependency_paths": [],
        }
        assert _git(workspace_path, "remote") == ""
        assert Path(
            _git(workspace_path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve() != Path(
            _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve()

    assert workspace_path is not None
    assert not workspace_path.exists()


def test_isolated_workspace_copies_node_dependencies_without_linking_canonical_files(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    dependency = root / "node_modules" / "example" / "index.js"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("module.exports = 1;\n", encoding="utf-8")
    manifest = collect_verification_input_manifest(root)

    with isolated_finish_workspace(
        root,
        input_manifest=manifest,
        commands=[{"argv": ["npm", "test"]}],
    ) as workspace:
        copied = workspace["root"] / "node_modules" / "example" / "index.js"
        assert workspace["public"]["copied_dependency_paths"] == ["node_modules"]
        copied.write_text("module.exports = 2;\n", encoding="utf-8")

    assert dependency.read_text(encoding="utf-8") == "module.exports = 1;\n"
