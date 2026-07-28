from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any

from .errors import InvalidInputError
from .paths import ProjectPaths


def capture_finish_repository_snapshot(
    paths: ProjectPaths,
    *,
    base_revision: str | None = None,
) -> dict[str, Any]:
    root = paths.root
    head = _git(root, ["rev-parse", "HEAD"]).strip()
    base = _git(root, ["rev-parse", base_revision or "HEAD"]).strip()
    tracked_diff = _git_bytes(
        root,
        [
            "diff",
            "--binary",
            "--no-ext-diff",
            base,
            "--",
            ".",
            ":(exclude).project-loop/**",
        ],
    )
    all_untracked = [
        line
        for line in _git(
            root,
            ["ls-files", "--others", "--exclude-standard", "-z"],
        ).split("\0")
        if line
    ]
    harness_untracked = [path for path in all_untracked if _is_harness_local_path(path)]
    untracked = [path for path in all_untracked if not _is_harness_local_path(path)]
    untracked_bytes = bytearray()
    for path_value in sorted(untracked):
        try:
            data = (root / path_value).read_bytes()
        except OSError as exc:
            raise InvalidInputError(
                "Repository changed while the Git snapshot was being captured.",
                details={"path": path_value, "reason": str(exc)},
            ) from exc
        name = path_value.encode("utf-8", errors="surrogateescape")
        untracked_bytes.extend(b"\0PCL-UNTRACKED\0" + str(len(name)).encode() + b":" + name)
        untracked_bytes.extend(b"\0" + str(len(data)).encode() + b":" + data)
    diff_bytes = tracked_diff + bytes(untracked_bytes)
    changes = _changed_paths(
        root,
        base=base,
        untracked=untracked,
        harness_local=False,
    )
    harness_local_state = _changed_paths(
        root,
        base=base,
        untracked=harness_untracked,
        harness_local=True,
    )
    return {
        "packet_repository": {
            "base_revision": base,
            "head_revision": head,
            "diff_sha256": f"sha256:{hashlib.sha256(diff_bytes).hexdigest()}",
            "dirty": bool(changes),
        },
        "changes": changes,
        "harness_local_state": harness_local_state,
    }


def _changed_paths(
    root: Path,
    *,
    base: str,
    untracked: list[str],
    harness_local: bool,
) -> list[dict[str, Any]]:
    pathspec = (
        [".project-loop"]
        if harness_local
        else [
            ".",
            ":(exclude).project-loop/**",
        ]
    )
    output = _git(
        root,
        ["diff", "--name-status", "--find-renames", base, "--", *pathspec],
    )
    changes: list[dict[str, Any]] = []
    mapping = {"A": "added", "M": "modified", "D": "deleted"}
    for line in output.splitlines():
        parts = line.split("\t")
        code = parts[0][0]
        if code == "R" and len(parts) == 3:
            changes.append(
                {
                    "path": parts[2],
                    "change_type": "renamed",
                    "previous_path": parts[1],
                }
            )
        elif code in mapping and len(parts) >= 2:
            changes.append(
                {
                    "path": parts[-1],
                    "change_type": mapping[code],
                    "previous_path": None,
                }
            )
    changes.extend(
        {
            "path": path_value,
            "change_type": "untracked",
            "previous_path": None,
        }
        for path_value in sorted(untracked)
    )
    return sorted(changes, key=lambda item: (item["path"], item["change_type"]))


def _is_harness_local_path(path: str) -> bool:
    return path == ".project-loop" or path.startswith(".project-loop/")


def _git(root: Path, args: list[str]) -> str:
    return _git_bytes(root, args).decode(
        "utf-8",
        errors="surrogateescape",
    )


def _git_bytes(root: Path, args: list[str]) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise InvalidInputError(
            "Could not resolve the Git repository snapshot.",
            details={
                "argv": ["git", *args],
                "exit_code": result.returncode,
                "stderr": result.stderr.decode(errors="replace"),
            },
        )
    return result.stdout
