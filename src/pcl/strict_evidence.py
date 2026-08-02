from __future__ import annotations

from dataclasses import dataclass
import ctypes
import errno
import os
from pathlib import Path
import stat
import sys
from typing import Sequence


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


@dataclass(frozen=True)
class StrictDirectoryWrite:
    path: Path
    expected_parent: Path
    parent_identity: tuple[int, int, int, int, int]
    directory_identity: tuple[int, int, int, int, int]
    staging_path: Path | None = None


def strict_inspect_canonical_directory(
    path: Path,
    *,
    expected_parent: Path,
) -> StrictDirectoryWrite:
    """Open one existing canonical directory and retain its exact identity."""
    if path.parent != expected_parent or path.name in {"", ".", ".."}:
        raise OSError(errno.EINVAL, "directory path is not canonical", str(path))
    parent_descriptor = _open_canonical_directory(expected_parent)
    try:
        matches = [
            existing
            for existing in os.listdir(parent_descriptor)
            if existing.casefold() == path.name.casefold()
        ]
        if not matches:
            raise FileNotFoundError(errno.ENOENT, "directory does not exist", str(path))
        if matches != [path.name]:
            raise OSError(errno.EEXIST, "directory path has a case collision", str(path))
        child_descriptor = _open_child_directory(
            path,
            parent_name=path.name,
            base_descriptor=parent_descriptor,
        )
        try:
            child = os.fstat(child_descriptor)
        finally:
            os.close(child_descriptor)
        return StrictDirectoryWrite(
            path=path,
            expected_parent=expected_parent,
            parent_identity=_directory_identity(os.fstat(parent_descriptor)),
            directory_identity=_directory_identity(child),
        )
    finally:
        os.close(parent_descriptor)


def strict_list_canonical_directory(receipt: StrictDirectoryWrite) -> tuple[str, ...]:
    """List an exact retained directory without following a replacement path."""
    parent_descriptor = _open_canonical_directory(receipt.expected_parent)
    child_descriptor: int | None = None
    try:
        child_descriptor = _open_child_directory(
            receipt.path,
            parent_name=receipt.path.name,
            base_descriptor=parent_descriptor,
        )
        before = os.fstat(child_descriptor)
        if _directory_identity(before) != receipt.directory_identity:
            raise OSError(errno.ESTALE, "directory identity changed")
        entries = tuple(os.listdir(child_descriptor))
        after = os.fstat(child_descriptor)
        if _directory_identity(before) != _directory_identity(after):
            raise OSError(errno.ESTALE, "directory changed while listing")
        return entries
    finally:
        if child_descriptor is not None:
            os.close(child_descriptor)
        os.close(parent_descriptor)


def strict_create_canonical_directory(
    path: Path,
    *,
    expected_parent: Path,
) -> StrictDirectoryWrite:
    """Create one exclusive canonical directory and retain its exact identity."""
    if path.parent != expected_parent or path.name in {"", ".", ".."}:
        raise OSError(errno.EINVAL, "directory path is not canonical", str(path))
    parent_descriptor = _open_canonical_directory(expected_parent)
    created = False
    try:
        _reject_case_alias(parent_descriptor, path.name)
        os.mkdir(path.name, mode=0o700, dir_fd=parent_descriptor)
        created = True
        os.fsync(parent_descriptor)
        child_descriptor = _open_child_directory(
            path,
            parent_name=path.name,
            base_descriptor=parent_descriptor,
        )
        try:
            child = os.fstat(child_descriptor)
        finally:
            os.close(child_descriptor)
        parent = os.fstat(parent_descriptor)
        return StrictDirectoryWrite(
            path=path,
            expected_parent=expected_parent,
            parent_identity=_directory_identity(parent),
            directory_identity=_directory_identity(child),
        )
    except BaseException:
        if created:
            try:
                os.rmdir(path.name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_descriptor)


def strict_publish_written_directory(
    receipt: StrictDirectoryWrite,
    *,
    final_path: Path,
) -> StrictDirectoryWrite:
    """Exclusively rename a retained staging directory and fsync its parent."""
    if (
        receipt.path.parent != receipt.expected_parent
        or final_path.parent != receipt.expected_parent
        or final_path.name in {"", ".", ".."}
    ):
        raise OSError(errno.EINVAL, "published directory path is not canonical")
    parent_descriptor = _open_canonical_directory(receipt.expected_parent)
    try:
        _reject_case_alias(parent_descriptor, final_path.name)
        current = os.stat(
            receipt.path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(current.st_mode)
            or _directory_object_identity(current)
            != _directory_object_identity_from_tuple(receipt.directory_identity)
        ):
            raise OSError(errno.ESTALE, "staging directory identity changed")
        _rename_directory_exclusive(
            parent_descriptor,
            receipt.path.name,
            final_path.name,
        )
        os.fsync(parent_descriptor)
        final = os.stat(
            final_path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(final.st_mode)
            or _directory_object_identity(final)
            != _directory_object_identity(current)
        ):
            raise OSError(errno.ESTALE, "published directory identity changed")
        parent = os.fstat(parent_descriptor)
        return StrictDirectoryWrite(
            path=final_path,
            expected_parent=receipt.expected_parent,
            parent_identity=_directory_identity(parent),
            directory_identity=_directory_identity(final),
            staging_path=receipt.path,
        )
    finally:
        os.close(parent_descriptor)


def strict_remove_written_directory(
    receipt: StrictDirectoryWrite,
    *,
    file_receipts: Sequence[StrictFileWrite] = (),
) -> bool:
    """Remove only retained files and an exact empty invocation-owned directory."""
    if receipt.path.parent != receipt.expected_parent:
        return False
    try:
        parent_descriptor = _open_canonical_directory(receipt.expected_parent)
    except OSError:
        return False
    child_descriptor: int | None = None
    try:
        parent = os.fstat(parent_descriptor)
        current = os.stat(
            receipt.path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            _directory_identity(parent) != receipt.parent_identity
            or not stat.S_ISDIR(current.st_mode)
            or _directory_identity(current) != receipt.directory_identity
        ):
            return False
        child_descriptor = _open_child_directory(
            receipt.path,
            parent_name=receipt.path.name,
            base_descriptor=parent_descriptor,
        )
        expected_names = tuple(file_receipt.path.name for file_receipt in file_receipts)
        actual_names = tuple(os.listdir(child_descriptor))
        if (
            set(actual_names) != set(expected_names)
            or len(actual_names) != len(expected_names)
            or len({name.casefold() for name in actual_names}) != len(actual_names)
        ):
            return False
        for file_receipt in file_receipts:
            source_parent = (
                receipt.staging_path
                if receipt.staging_path is not None
                else receipt.path
            )
            if file_receipt.expected_parent != source_parent:
                return False
            file_stat = os.stat(
                file_receipt.path.name,
                dir_fd=child_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_nlink != 1
                or _file_identity(file_stat) != file_receipt.file_identity
            ):
                return False
        for file_receipt in file_receipts:
            os.unlink(file_receipt.path.name, dir_fd=child_descriptor)
        os.fsync(child_descriptor)
        os.close(child_descriptor)
        child_descriptor = None
        os.rmdir(receipt.path.name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
        return True
    except (FileNotFoundError, OSError):
        return False
    finally:
        if child_descriptor is not None:
            os.close(child_descriptor)
        os.close(parent_descriptor)


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
            or file_path_stat.st_nlink != 1
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
                or current.st_nlink != 1
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
    if file_before.st_nlink != 1:
        return StrictFileRead("hardlink")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
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


def _reject_case_alias(descriptor: int, name: str) -> None:
    for existing in os.listdir(descriptor):
        if existing.casefold() == name.casefold():
            if existing == name:
                raise FileExistsError(errno.EEXIST, "directory already exists", name)
            raise OSError(errno.EEXIST, "case-alias directory already exists", name)


def _rename_directory_exclusive(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if sys.platform == "darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            raise OSError(errno.ENOTSUP, "exclusive directory publish is unsupported")
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        outcome = renameatx_np(
            parent_descriptor,
            source,
            parent_descriptor,
            destination,
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "exclusive directory publish is unsupported")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        outcome = renameat2(
            parent_descriptor,
            source,
            parent_descriptor,
            destination,
            1,  # RENAME_NOREPLACE
        )
    else:
        raise OSError(errno.ENOTSUP, "exclusive directory publish is unsupported")
    if outcome != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination_name)


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


def _directory_object_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _directory_object_identity_from_tuple(
    value: tuple[int, int, int, int, int],
) -> tuple[int, int]:
    return value[0], value[1]


def _errno_detail(exc: OSError) -> str:
    return f"errno={exc.errno}" if exc.errno is not None else "os_error"
