from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Iterable

from .errors import InvalidInputError
from .timeutil import utc_now_iso


VERIFICATION_INPUT_MANIFEST_VERSION = "verification-input-manifest/v1"
VERIFICATION_EFFECT_CLASSIFICATIONS = frozenset(
    {"read_only", "declared_outputs", "mutates_inputs", "unknown"}
)
_HARNESS_LOCAL_PREFIX = ".project-loop"


class _InputChangedDuringCollection(Exception):
    pass


def collect_verification_input_manifest(
    root: Path,
    *,
    declared_output_patterns: Iterable[str] = (),
) -> dict[str, Any]:
    """Collect deterministic Git-backed verification inputs without mutating state."""

    canonical_root = root.resolve()
    patterns = tuple(sorted(set(str(pattern) for pattern in declared_output_patterns)))
    repository_root = Path(_git(canonical_root, "rev-parse", "--show-toplevel").strip()).resolve()
    if repository_root != canonical_root:
        raise InvalidInputError(
            "Verification input root must be the Git repository root.",
            details={
                "root": str(canonical_root),
                "repository_root": str(repository_root),
            },
        )
    head = _git(canonical_root, "rev-parse", "HEAD").strip()
    tracked = _git_paths(canonical_root, "ls-files", "--cached")
    untracked = _git_paths(
        canonical_root,
        "ls-files",
        "--others",
        "--exclude-standard",
    )
    ignored = (
        _git_paths(
            canonical_root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
        )
        if patterns
        else []
    )

    sources: dict[str, str] = {}
    for path in tracked:
        if not _is_harness_local_path(path):
            sources[path] = "tracked"
    for path in untracked:
        if not _is_harness_local_path(path):
            sources.setdefault(path, "untracked")
    for path in ignored:
        if not _is_harness_local_path(path) and _matches_any(path, patterns):
            sources.setdefault(path, "ignored_output")

    entries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for relative_path, source in sorted(sources.items()):
        try:
            entry = _capture_path(canonical_root, relative_path, source=source)
        except FileNotFoundError as exc:
            if source == "tracked":
                entry = _missing_entry(relative_path, source=source)
            else:
                errors.append(
                    _collection_error(
                        relative_path,
                        "input_changed_during_collection",
                        exc,
                    )
                )
                continue
        except _InputChangedDuringCollection as exc:
            errors.append(
                {
                    "path": relative_path,
                    "code": "input_changed_during_collection",
                    "message": str(exc),
                }
            )
            continue
        except PermissionError as exc:
            errors.append(_collection_error(relative_path, "input_unreadable", exc))
            continue
        except OSError as exc:
            errors.append(_collection_error(relative_path, "input_unreadable", exc))
            continue
        if entry is None:
            errors.append(
                {
                    "path": relative_path,
                    "code": "unsupported_input_type",
                    "message": "Unsupported filesystem input type.",
                }
            )
            continue
        entries.append(entry)

    manifest: dict[str, Any] = {
        "contract_version": VERIFICATION_INPUT_MANIFEST_VERSION,
        "manifest_sha256": "",
        "collected_at": utc_now_iso(),
        "root": str(canonical_root),
        "repository": {
            "base_revision": head,
            "head_revision": head,
        },
        "declared_output_patterns": list(patterns),
        "entries": entries,
        "excluded": [
            {"path": ".project-loop/**", "reason": "harness_local_state"}
        ],
        "errors": errors,
        "ok": not errors,
    }
    manifest["manifest_sha256"] = _manifest_sha256(manifest)
    return manifest


def compare_verification_input_manifests(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Classify filesystem effects between two v1 verification manifests."""

    _require_manifest(before, label="before")
    _require_manifest(after, label="after")
    reasons = _error_reasons(before, label="before") + _error_reasons(after, label="after")
    if reasons:
        return {
            "classification": "unknown",
            "changes": [],
            "reasons": reasons,
        }

    before_entries = {str(item["path"]): item for item in before["entries"]}
    after_entries = {str(item["path"]): item for item in after["entries"]}
    changes: list[dict[str, Any]] = []
    for path in sorted(set(before_entries) | set(after_entries)):
        before_entry = before_entries.get(path)
        after_entry = after_entries.get(path)
        if before_entry == after_entry:
            continue
        changes.append(
            {
                "path": path,
                "before_source": None if before_entry is None else before_entry["source"],
                "after_source": None if after_entry is None else after_entry["source"],
                "change": (
                    "added"
                    if before_entry is None
                    else "deleted"
                    if after_entry is None
                    else "modified"
                ),
            }
        )

    if not changes:
        classification = "read_only"
    elif all(
        item["before_source"] in {None, "ignored_output"}
        and item["after_source"] in {None, "ignored_output"}
        for item in changes
    ):
        classification = "declared_outputs"
    else:
        classification = "mutates_inputs"
    return {
        "classification": classification,
        "changes": changes,
        "reasons": [],
    }


def canonical_verification_input_manifest_json(manifest: dict[str, Any]) -> str:
    _require_manifest(manifest, label="manifest")
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _capture_path(
    root: Path,
    relative_path: str,
    *,
    source: str,
) -> dict[str, Any] | None:
    path = root / relative_path
    before = os.lstat(path)
    mode = f"{stat.S_IMODE(before.st_mode):04o}"
    if stat.S_ISLNK(before.st_mode):
        target = os.readlink(path)
        after = os.lstat(path)
        if _stat_identity(before) != _stat_identity(after):
            raise _InputChangedDuringCollection(
                "Filesystem input changed while its symlink target was read."
            )
        return {
            "path": relative_path,
            "source": source,
            "kind": "symlink",
            "mode": mode,
            "size": before.st_size,
            "sha256": None,
            "symlink_target": target,
        }
    if not stat.S_ISREG(before.st_mode):
        return None
    digest, opened, after = _hash_regular_file(path)
    final = os.lstat(path)
    if (
        _stat_identity(before) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(final)
    ):
        raise _InputChangedDuringCollection(
            "Filesystem input changed while its bytes were read."
        )
    return {
        "path": relative_path,
        "source": source,
        "kind": "file",
        "mode": mode,
        "size": after.st_size,
        "sha256": f"sha256:{digest}",
        "symlink_target": None,
    }


def _hash_regular_file(path: Path) -> tuple[str, os.stat_result, os.stat_result]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), opened, after


def _missing_entry(relative_path: str, *, source: str) -> dict[str, Any]:
    return {
        "path": relative_path,
        "source": source,
        "kind": "missing",
        "mode": None,
        "size": None,
        "sha256": None,
        "symlink_target": None,
    }


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _manifest_sha256(manifest: dict[str, Any]) -> str:
    semantic = {
        key: value
        for key, value in manifest.items()
        if key not in {"collected_at", "manifest_sha256"}
    }
    encoded = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_manifest(value: dict[str, Any], *, label: str) -> None:
    if value.get("contract_version") != VERIFICATION_INPUT_MANIFEST_VERSION:
        raise InvalidInputError(
            f"{label} is not a {VERIFICATION_INPUT_MANIFEST_VERSION} artifact.",
            details={"contract_version": value.get("contract_version")},
        )
    expected = _manifest_sha256(value)
    if value.get("manifest_sha256") != expected:
        raise InvalidInputError(
            f"{label} verification input manifest digest does not match its content.",
            details={
                "recorded": value.get("manifest_sha256"),
                "actual": expected,
            },
        )


def _error_reasons(manifest: dict[str, Any], *, label: str) -> list[dict[str, str]]:
    return [
        {
            "manifest": label,
            "path": str(item.get("path") or ""),
            "code": str(item.get("code") or "unknown"),
        }
        for item in manifest.get("errors", [])
    ]


def _collection_error(
    relative_path: str,
    code: str,
    exc: BaseException,
) -> dict[str, str]:
    return {
        "path": relative_path,
        "code": code,
        "message": f"{exc.__class__.__name__}: {exc}",
    }


def _git_paths(root: Path, *args: str) -> list[str]:
    output = _git_bytes(root, *args, "-z")
    return sorted(
        path.decode("utf-8", errors="surrogateescape")
        for path in output.split(b"\0")
        if path
    )


def _git(root: Path, *args: str) -> str:
    return _git_bytes(root, *args).decode("utf-8", errors="surrogateescape")


def _git_bytes(root: Path, *args: str) -> bytes:
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
            "Could not collect the Git-backed verification input manifest.",
            details={
                "argv": ["git", *args],
                "exit_code": result.returncode,
                "stderr": result.stderr.decode("utf-8", errors="replace"),
            },
        )
    return result.stdout


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_harness_local_path(path: str) -> bool:
    return path == _HARNESS_LOCAL_PREFIX or path.startswith(
        f"{_HARNESS_LOCAL_PREFIX}/"
    )
