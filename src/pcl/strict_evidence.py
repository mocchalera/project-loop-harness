from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat


@dataclass(frozen=True)
class StrictFileRead:
    status: str
    content: bytes | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def strict_read_canonical_file(
    path: Path,
    *,
    expected_parent: Path,
    expected_size: int | None = None,
) -> StrictFileRead:
    """Read one canonical regular file once and detect path/identity changes."""
    if path.parent != expected_parent:
        return StrictFileRead("path_invalid")

    try:
        parent_before = os.lstat(expected_parent)
    except FileNotFoundError:
        return StrictFileRead("directory_missing")
    except OSError as exc:
        return StrictFileRead("directory_unreadable", detail=_errno_detail(exc))
    if stat.S_ISLNK(parent_before.st_mode):
        return StrictFileRead("directory_symlink")
    if not stat.S_ISDIR(parent_before.st_mode):
        return StrictFileRead("directory_not_directory")
    try:
        if expected_parent.resolve() != expected_parent.absolute():
            return StrictFileRead("directory_redirected")
    except OSError as exc:
        return StrictFileRead("directory_unreadable", detail=_errno_detail(exc))

    try:
        file_before = os.lstat(path)
    except FileNotFoundError:
        return StrictFileRead("missing")
    except OSError as exc:
        return StrictFileRead("unreadable", detail=_errno_detail(exc))
    if stat.S_ISLNK(file_before.st_mode):
        return StrictFileRead("symlink")
    if not stat.S_ISREG(file_before.st_mode):
        return StrictFileRead("not_regular")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or _file_identity(file_before) != _file_identity(opened)
            ):
                return StrictFileRead("changed")
            if expected_size is not None and opened.st_size != expected_size:
                return StrictFileRead("size_mismatch")
            content = stream.read()
            after = os.fstat(stream.fileno())
        current = os.lstat(path)
        parent_after = os.lstat(expected_parent)
    except FileNotFoundError:
        return StrictFileRead("missing")
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return StrictFileRead("symlink")
        return StrictFileRead("unreadable", detail=_errno_detail(exc))

    if (
        _file_identity(opened) != _file_identity(after)
        or _file_identity(after) != _file_identity(current)
        or _directory_identity(parent_before) != _directory_identity(parent_after)
    ):
        return StrictFileRead("changed")
    if expected_size is not None and len(content) != expected_size:
        return StrictFileRead("size_mismatch")
    return StrictFileRead("ok", content=content)


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return _file_identity(value)


def _errno_detail(exc: OSError) -> str:
    return f"errno={exc.errno}" if exc.errno is not None else "os_error"
