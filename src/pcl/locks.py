from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
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


class AdvisoryLock:
    def __init__(self, path: Path, *, exclusive: bool, timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS) -> None:
        self.path = path
        self.exclusive = exclusive
        self.timeout_ms = timeout_ms
        self._fd: int | None = None
        self._backend: str | None = None

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
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
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
            os.close(fd)
            raise

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd, backend = self._fd, None, self._backend
        self._backend = None
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
) -> Iterator[AdvisoryLock]:
    with AdvisoryLock(loop_dir / "project.lock", exclusive=exclusive, timeout_ms=timeout_ms) as lock:
        yield lock


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
