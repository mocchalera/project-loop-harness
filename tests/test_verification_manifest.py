from __future__ import annotations

import os
from pathlib import Path
import subprocess

from pcl import verification_manifest
from pcl.verification_manifest import (
    collect_verification_input_manifest,
    compare_verification_input_manifests,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "pcl-test@example.invalid")
    _git(tmp_path, "config", "user.name", "PCL Test")
    (tmp_path / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "source.py")
    _git(tmp_path, "commit", "-qm", "fixture")
    return tmp_path


def _entry(manifest: dict, path: str) -> dict:
    return next(item for item in manifest["entries"] if item["path"] == path)


def test_manifest_is_deterministic_and_detects_tracked_content_and_mode_changes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)

    first = collect_verification_input_manifest(root)
    same = collect_verification_input_manifest(root)

    assert first["ok"] is True
    assert first["contract_version"] == "verification-input-manifest/v1"
    assert first["manifest_sha256"] == same["manifest_sha256"]
    assert _entry(first, "source.py") == {
        "path": "source.py",
        "source": "tracked",
        "kind": "file",
        "mode": "0644",
        "size": 10,
        "sha256": "sha256:e13df8c44af5dea1e412403910b99cc5a48f2ccbf68a66b3374d6ab9cef9fc65",
        "symlink_target": None,
    }
    assert compare_verification_input_manifests(first, same) == {
        "classification": "read_only",
        "changes": [],
        "reasons": [],
    }

    (root / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
    os.chmod(root / "source.py", 0o755)
    changed = collect_verification_input_manifest(root)
    comparison = compare_verification_input_manifests(first, changed)

    assert comparison["classification"] == "mutates_inputs"
    assert comparison["changes"] == [
        {
            "path": "source.py",
            "before_source": "tracked",
            "after_source": "tracked",
            "change": "modified",
        }
    ]


def test_manifest_batches_repository_root_and_head_observation(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    original = verification_manifest.INHERITED_GIT_RUNNER
    calls: list[tuple[str, ...]] = []

    class RecordingGit:
        def run(self, cwd, *args, input_bytes=None):
            calls.append(tuple(args))
            return original.run(cwd, *args, input_bytes=input_bytes)

    manifest = collect_verification_input_manifest(root, git_runner=RecordingGit())

    assert manifest["ok"] is True
    assert calls == [
        ("rev-parse", "--show-toplevel", "HEAD"),
        ("ls-files", "--cached", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ]


def test_manifest_detects_symlink_target_and_untracked_changes(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "target-a.txt").write_text("a\n", encoding="utf-8")
    (root / "target-b.txt").write_text("b\n", encoding="utf-8")
    (root / "current.txt").symlink_to("target-a.txt")
    _git(root, "add", "target-a.txt", "target-b.txt", "current.txt")
    _git(root, "commit", "-qm", "symlink fixture")
    before = collect_verification_input_manifest(root)

    (root / "current.txt").unlink()
    (root / "current.txt").symlink_to("target-b.txt")
    (root / "notes.txt").write_text("untracked\n", encoding="utf-8")
    after = collect_verification_input_manifest(root)
    comparison = compare_verification_input_manifests(before, after)

    assert _entry(before, "current.txt")["symlink_target"] == "target-a.txt"
    assert _entry(after, "current.txt")["symlink_target"] == "target-b.txt"
    assert _entry(after, "notes.txt")["source"] == "untracked"
    assert comparison["classification"] == "mutates_inputs"
    assert [(item["path"], item["change"]) for item in comparison["changes"]] == [
        ("current.txt", "modified"),
        ("notes.txt", "added"),
    ]


def test_manifest_classifies_only_policy_matched_ignored_changes_as_declared_outputs(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    (root / ".gitignore").write_text("__pycache__/\n.project-loop/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-qm", "ignore outputs")
    before = collect_verification_input_manifest(
        root,
        declared_output_patterns=("__pycache__/**",),
    )

    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "source.pyc").write_bytes(b"cache")
    (root / ".project-loop").mkdir()
    (root / ".project-loop" / "project.db").write_bytes(b"local state")
    after = collect_verification_input_manifest(
        root,
        declared_output_patterns=("__pycache__/**",),
    )
    comparison = compare_verification_input_manifests(before, after)

    assert _entry(after, "__pycache__/source.pyc")["source"] == "ignored_output"
    assert all(not item["path"].startswith(".project-loop") for item in after["entries"])
    assert after["excluded"] == [
        {"path": ".project-loop/**", "reason": "harness_local_state"}
    ]
    assert comparison == {
        "classification": "declared_outputs",
        "changes": [
            {
                "path": "__pycache__/source.pyc",
                "before_source": None,
                "after_source": "ignored_output",
                "change": "added",
            }
        ],
        "reasons": [],
    }


def test_manifest_fails_closed_when_a_file_cannot_be_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _repository(tmp_path)
    before = collect_verification_input_manifest(root)
    original_open = verification_manifest.os.open

    def deny_source(path, flags, *args, **kwargs):
        if Path(path) == root / "source.py":
            raise PermissionError("injected unreadable input")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(verification_manifest.os, "open", deny_source)
    unreadable = collect_verification_input_manifest(root)
    comparison = compare_verification_input_manifests(before, unreadable)

    assert unreadable["ok"] is False
    assert unreadable["errors"] == [
        {
            "path": "source.py",
            "code": "input_unreadable",
            "message": "PermissionError: injected unreadable input",
        }
    ]
    assert comparison["classification"] == "unknown"
    assert comparison["changes"] == []
    assert comparison["reasons"] == [
        {
            "manifest": "after",
            "path": "source.py",
            "code": "input_unreadable",
        }
    ]


def test_manifest_fails_closed_when_path_is_replaced_after_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _repository(tmp_path)
    original_hash = verification_manifest._hash_regular_file

    def hash_then_replace(path):
        result = original_hash(path)
        if path == root / "source.py":
            replacement = root / "replacement.py"
            replacement.write_text("VALUE = 9\n", encoding="utf-8")
            replacement.replace(path)
        return result

    monkeypatch.setattr(verification_manifest, "_hash_regular_file", hash_then_replace)

    manifest = collect_verification_input_manifest(root)

    assert manifest["ok"] is False
    assert manifest["errors"] == [
        {
            "path": "source.py",
            "code": "input_changed_during_collection",
            "message": "Filesystem input changed while its bytes were read.",
        }
    ]


def test_manifest_fails_closed_for_unsupported_special_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _repository(tmp_path)
    os.mkfifo(root / "worker.pipe")
    original_git_paths = verification_manifest._git_paths

    def include_special_file(path, *args):
        result = original_git_paths(path, *args)
        if "--others" in args and "--ignored" not in args:
            return [*result, "worker.pipe"]
        return result

    monkeypatch.setattr(verification_manifest, "_git_paths", include_special_file)

    manifest = collect_verification_input_manifest(root)

    assert manifest["ok"] is False
    assert manifest["errors"] == [
        {
            "path": "worker.pipe",
            "code": "unsupported_input_type",
            "message": "Unsupported filesystem input type.",
        }
    ]
    assert all(item["path"] != "worker.pipe" for item in manifest["entries"])
