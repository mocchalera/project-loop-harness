from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Any, Iterator

from .errors import InvalidInputError
from .verification_manifest import canonical_verification_input_manifest_json


NODE_EXECUTABLES = frozenset({"bun", "node", "npm", "pnpm", "yarn"})


@contextmanager
def isolated_finish_workspace(
    canonical_root: Path,
    *,
    input_manifest: dict[str, Any],
    commands: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Materialize the captured working tree into an independent local clone."""

    canonical_verification_input_manifest_json(input_manifest)
    if not input_manifest.get("ok"):
        raise InvalidInputError(
            "Cannot prepare an isolated finish workspace from an unhealthy input manifest.",
            details={
                "contract_version": input_manifest.get("contract_version"),
                "manifest_sha256": input_manifest.get("manifest_sha256"),
                "errors": input_manifest.get("errors", []),
            },
        )
    temporary_root = Path(tempfile.mkdtemp(prefix="pcl-finish-workspace-"))
    workspace_root = temporary_root / "repository"
    try:
        _git_clone(canonical_root.resolve(), workspace_root)
        _materialize_entries(
            canonical_root.resolve(),
            workspace_root,
            input_manifest["entries"],
        )
        copied_dependencies = _copy_required_local_dependencies(
            canonical_root.resolve(),
            workspace_root,
            commands,
        )
        yield {
            "root": workspace_root,
            "public": {
                "kind": "independent_git_copy",
                "temporary": True,
                "git_metadata_shared": False,
                "input_manifest_sha256": input_manifest["manifest_sha256"],
                "copied_dependency_paths": copied_dependencies,
            },
        }
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _git_clone(canonical_root: Path, workspace_root: Path) -> None:
    _run_git(
        canonical_root.parent,
        "clone",
        "--quiet",
        "--no-local",
        "--no-checkout",
        str(canonical_root),
        str(workspace_root),
    )
    _run_git(
        workspace_root,
        "checkout",
        "--quiet",
        "--detach",
        "HEAD",
    )
    _run_git(workspace_root, "remote", "remove", "origin")
    git_common_dir = _run_git(
        workspace_root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    ).strip()
    canonical_common_dir = _run_git(
        canonical_root,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    ).strip()
    if Path(git_common_dir).resolve() == Path(canonical_common_dir).resolve():
        raise InvalidInputError(
            "Isolated finish workspace unexpectedly shares canonical Git metadata.",
            details={
                "canonical_git_common_dir": canonical_common_dir,
                "workspace_git_common_dir": git_common_dir,
            },
        )


def _materialize_entries(
    canonical_root: Path,
    workspace_root: Path,
    entries: list[dict[str, Any]],
) -> None:
    for entry in entries:
        if entry.get("source") == "ignored_output":
            continue
        relative_path = _safe_relative_path(str(entry["path"]))
        source = canonical_root.joinpath(*relative_path.parts)
        destination = workspace_root.joinpath(*relative_path.parts)
        _remove_existing(destination)
        if entry.get("kind") == "missing":
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if entry.get("kind") == "symlink":
            os.symlink(os.readlink(source), destination)
            continue
        if entry.get("kind") != "file":
            raise InvalidInputError(
                "Verification input manifest contains an unsupported workspace entry.",
                details={"path": str(relative_path), "kind": entry.get("kind")},
            )
        shutil.copy2(source, destination, follow_symlinks=False)


def _copy_required_local_dependencies(
    canonical_root: Path,
    workspace_root: Path,
    commands: list[dict[str, Any]],
) -> list[str]:
    executables = {
        Path(str(command.get("argv", [""])[0])).name
        for command in commands
        if command.get("argv")
    }
    copied: list[str] = []
    if executables & NODE_EXECUTABLES:
        source = canonical_root / "node_modules"
        if source.is_dir() and not source.is_symlink():
            destination = workspace_root / "node_modules"
            shutil.copytree(source, destination, symlinks=True)
            copied.append("node_modules")
    return copied


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise InvalidInputError(
            "Verification input manifest contains an unsafe path.",
            details={"path": value},
        )
    return path


def _remove_existing(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _run_git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        text=True,
    )
    if result.returncode != 0:
        raise InvalidInputError(
            "Could not prepare the isolated finish workspace.",
            details={
                "argv": ["git", *args],
                "exit_code": result.returncode,
                "stderr": result.stderr,
            },
        )
    return result.stdout
