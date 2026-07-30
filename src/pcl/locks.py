from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import threading
import time
from typing import Iterator

from .db import SQLITE_BUSY_TIMEOUT_MS
from .errors import DataStoreError

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on unsupported platforms
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised through platform mocks
    msvcrt = None  # type: ignore[assignment]


_CAPABILITY_ISSUER = object()


class _ExclusiveProjectOperationCapability:
    __slots__ = ()

    def __new__(cls, issuer: object = None) -> _ExclusiveProjectOperationCapability:
        if issuer is not _CAPABILITY_ISSUER:
            raise TypeError(
                "Exclusive project-operation capabilities are issued only by "
                "project_operation_lock()."
            )
        return super().__new__(cls)


@dataclass(frozen=True)
class _ActiveExclusiveProjectOperation:
    capability: _ExclusiveProjectOperationCapability
    lock: AdvisoryLock
    descriptor: int
    owner_pid: int
    owner_thread_id: int
    root_identity: tuple[int, int, int]
    loop_identity: tuple[int, int, int]
    lock_identity: tuple[int, int, int]


_ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS: dict[
    int,
    _ActiveExclusiveProjectOperation,
] = {}


class AdvisoryLock:
    def __init__(self, path: Path, *, exclusive: bool, timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS) -> None:
        self.path = path
        self.exclusive = exclusive
        self.timeout_ms = timeout_ms
        self._fd: int | None = None
        self._backend: str | None = None
        self._capability: _ExclusiveProjectOperationCapability | None = None

    def acquire(self) -> None:
        windows = os.name == "nt"
        if windows and msvcrt is None:
            raise DataStoreError(
                "Project operation locks are unsupported on this platform.",
                details={"path": str(self.path), "capability": "msvcrt.locking"},
            )
        if not windows and fcntl is None:
            raise DataStoreError(
                "Project operation locks are unsupported on this platform.",
                details={"path": str(self.path), "capability": "fcntl.flock"},
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        issues_capability = self.exclusive and self.path.name == "project.lock"
        capability_root_identity = (
            _directory_identity(
                os.stat(self.path.parent.parent, follow_symlinks=True)
            )
            if issues_capability
            else None
        )
        capability_loop_identity = (
            _directory_identity(os.stat(self.path.parent, follow_symlinks=True))
            if issues_capability
            else None
        )
        open_flags = (
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(self.path, open_flags, 0o600)
        operation = None
        if not windows:
            assert fcntl is not None
            operation = (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        deadline = time.monotonic() + self.timeout_ms / 1000
        try:
            while True:
                try:
                    if windows:
                        assert msvcrt is not None
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        assert fcntl is not None and operation is not None
                        fcntl.flock(fd, operation)
                    self._fd = fd
                    self._backend = "msvcrt" if windows else "fcntl"
                    if (
                        capability_root_identity is not None
                        and capability_loop_identity is not None
                    ):
                        current_root_identity = _directory_identity(
                            os.stat(
                                self.path.parent.parent,
                                follow_symlinks=True,
                            )
                        )
                        current_loop_identity = _directory_identity(
                            os.stat(self.path.parent, follow_symlinks=True)
                        )
                        held_lock_identity = _file_identity(os.fstat(fd))
                        current_lock_identity = _file_identity(
                            os.stat(self.path, follow_symlinks=False)
                        )
                        if (
                            current_root_identity != capability_root_identity
                            or current_loop_identity != capability_loop_identity
                            or current_lock_identity != held_lock_identity
                        ):
                            raise DataStoreError(
                                "Project identity changed while acquiring the "
                                "project-operation lock.",
                                details={"path": str(self.path)},
                            )
                        capability = _ExclusiveProjectOperationCapability(
                            _CAPABILITY_ISSUER
                        )
                        active_operation = _ActiveExclusiveProjectOperation(
                            capability=capability,
                            lock=self,
                            descriptor=fd,
                            owner_pid=os.getpid(),
                            owner_thread_id=threading.get_ident(),
                            root_identity=capability_root_identity,
                            loop_identity=capability_loop_identity,
                            lock_identity=held_lock_identity,
                        )
                        _ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS[id(capability)] = (
                            active_operation
                        )
                        self._capability = capability
                    return
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise DataStoreError(
                            "Timed out acquiring project operation lock.",
                            details={
                                "path": str(self.path),
                                "exclusive": self.exclusive,
                                "timeout_ms": self.timeout_ms,
                            },
                        ) from exc
                    time.sleep(0.05)
        except BaseException:
            capability = self._capability
            self._capability = None
            self._fd = None
            self._backend = None
            if capability is not None:
                active = _ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS.get(id(capability))
                if active is not None and active.capability is capability:
                    _ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS.pop(id(capability), None)
            os.close(fd)
            raise

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd, backend = self._fd, None, self._backend
        self._backend = None
        capability = self._capability
        self._capability = None
        if capability is not None:
            active = _ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS.get(id(capability))
            if active is not None and active.capability is capability:
                _ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS.pop(id(capability), None)
        try:
            if backend == "msvcrt":
                assert msvcrt is not None
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                assert backend == "fcntl" and fcntl is not None
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> AdvisoryLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@contextmanager
def project_operation_lock(
    loop_dir: Path,
    *,
    exclusive: bool,
    timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
) -> Iterator[_ExclusiveProjectOperationCapability | None]:
    with AdvisoryLock(loop_dir / "project.lock", exclusive=exclusive, timeout_ms=timeout_ms) as lock:
        yield lock._capability


def require_live_exclusive_project_operation_capability(
    capability: object,
    *,
    loop_dir: Path,
) -> None:
    if not isinstance(capability, _ExclusiveProjectOperationCapability):
        raise _invalid_project_operation_capability(loop_dir)
    active = _ACTIVE_EXCLUSIVE_PROJECT_OPERATIONS.get(id(capability))
    if active is None or active.capability is not capability:
        raise _invalid_project_operation_capability(loop_dir)
    lock = active.lock
    try:
        current_root_identity = _directory_identity(
            os.stat(loop_dir.parent, follow_symlinks=True)
        )
        current_loop_identity = _directory_identity(
            os.stat(loop_dir, follow_symlinks=True)
        )
        held_lock_identity = _file_identity(os.fstat(active.descriptor))
        current_lock_identity = _file_identity(
            os.stat(loop_dir / "project.lock", follow_symlinks=False)
        )
    except OSError as exc:
        raise _invalid_project_operation_capability(loop_dir) from exc
    if (
        lock._fd != active.descriptor
        or not lock.exclusive
        or lock._capability is not capability
        or lock.path.name != "project.lock"
        or lock._backend is None
        or active.owner_pid != os.getpid()
        or active.owner_thread_id != threading.get_ident()
        or current_root_identity != active.root_identity
        or current_loop_identity != active.loop_identity
        or held_lock_identity != active.lock_identity
        or current_lock_identity != active.lock_identity
    ):
        raise _invalid_project_operation_capability(loop_dir)


@contextmanager
def jsonl_projector_lock(
    loop_dir: Path,
    *,
    timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
) -> Iterator[AdvisoryLock]:
    with AdvisoryLock(
        loop_dir / "events-jsonl.lock",
        exclusive=True,
        timeout_ms=timeout_ms,
    ) as lock:
        yield lock


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode & 0o170000)


def _file_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode & 0o170000)


def _invalid_project_operation_capability(loop_dir: Path) -> DataStoreError:
    return DataStoreError(
        "A live exclusive project-operation lock capability is required.",
        details={"loop_dir": str(loop_dir)},
    )
