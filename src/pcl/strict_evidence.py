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


@dataclass(frozen=True)
class StrictFileWrite:
    path: Path
    expected_parent: Path
    parent_identity: tuple[int, int, int, int, int]
    file_identity: tuple[int, int, int, int, int]


def strict_write_new_canonical_file(
    path: Path,
    *,
    expected_parent: Path,
    content: bytes,
) -> StrictFileWrite:
    """Create one canonical file without following directory or file symlinks."""
    if path.parent != expected_parent or path.name in {"", ".", ".."}:
        raise OSError(errno.EINVAL, "artifact path is not canonical", str(path))

    base = expected_parent.parent
    base_descriptor = _open_canonical_directory(base)
    parent_descriptor: int | None = None
    temporary_name = f"{path.name}.tmp"
    temporary_created = False
    final_created = False
    try:
        try:
            os.mkdir(expected_parent.name, mode=0o700, dir_fd=base_descriptor)
        except FileExistsError:
            pass
        parent_descriptor = _open_child_directory(
            expected_parent,
            parent_name=expected_parent.name,
            base_descriptor=base_descriptor,
        )
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_created = True
        try:
            with os.fdopen(file_descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)

        os.link(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        final_created = True
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        temporary_created = False
        os.fsync(parent_descriptor)

        parent_path_stat = os.lstat(expected_parent)
        parent_open_stat = os.fstat(parent_descriptor)
        file_path_stat = os.lstat(path)
        file_open_stat = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_path_stat.st_mode)
            or _directory_identity(parent_path_stat) != _directory_identity(parent_open_stat)
            or not stat.S_ISREG(file_path_stat.st_mode)
            or _file_identity(file_path_stat) != _file_identity(file_open_stat)
        ):
            raise OSError(errno.ESTALE, "artifact path changed during creation", str(path))
        return StrictFileWrite(
            path=path,
            expected_parent=expected_parent,
            parent_identity=_directory_identity(parent_path_stat),
            file_identity=_file_identity(file_path_stat),
        )
    except BaseException:
        if parent_descriptor is not None:
            if temporary_created:
                _unlink_if_present(parent_descriptor, temporary_name)
            if final_created:
                _unlink_if_present(parent_descriptor, path.name)
        raise
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        os.close(base_descriptor)


def strict_remove_written_file(receipt: StrictFileWrite) -> bool:
    """Remove only the exact canonical file created by a prior strict write."""
    if receipt.path.parent != receipt.expected_parent:
        return False
    try:
        parent_before = os.lstat(receipt.expected_parent)
        if (
            not stat.S_ISDIR(parent_before.st_mode)
            or _directory_identity(parent_before) != receipt.parent_identity
            or receipt.expected_parent.resolve() != receipt.expected_parent.absolute()
        ):
            return False
        descriptor = os.open(
            receipt.expected_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            parent_open = os.fstat(descriptor)
            current = os.stat(receipt.path.name, dir_fd=descriptor, follow_symlinks=False)
            if (
                _directory_identity(parent_open) != receipt.parent_identity
                or not stat.S_ISREG(current.st_mode)
                or _file_identity(current) != receipt.file_identity
            ):
                return False
            os.unlink(receipt.path.name, dir_fd=descriptor)
            os.fsync(descriptor)
            return True
        finally:
            os.close(descriptor)
    except (FileNotFoundError, OSError):
        return False


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


def _open_canonical_directory(path: Path) -> int:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise OSError(errno.ENOTDIR, "artifact base is not a canonical directory", str(path))
    if path.resolve() != path.absolute():
        raise OSError(errno.ELOOP, "artifact base directory is redirected", str(path))
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    opened = os.fstat(descriptor)
    if _directory_identity(before) != _directory_identity(opened):
        os.close(descriptor)
        raise OSError(errno.ESTALE, "artifact base changed while opening", str(path))
    return descriptor


def _open_child_directory(
    path: Path,
    *,
    parent_name: str,
    base_descriptor: int,
) -> int:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise OSError(errno.ENOTDIR, "artifact directory is not canonical", str(path))
    if path.resolve() != path.absolute():
        raise OSError(errno.ELOOP, "artifact directory is redirected", str(path))
    descriptor = os.open(
        parent_name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=base_descriptor,
    )
    opened = os.fstat(descriptor)
    if _directory_identity(before) != _directory_identity(opened):
        os.close(descriptor)
        raise OSError(errno.ESTALE, "artifact directory changed while opening", str(path))
    return descriptor


def _unlink_if_present(descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=descriptor)
    except FileNotFoundError:
        pass


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
