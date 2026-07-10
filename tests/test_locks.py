from __future__ import annotations

import errno
from pathlib import Path

import pytest

from pcl.errors import DataStoreError
import pcl.locks as locks


class FakeMsvcrt:
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, failures: list[int] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append((fd, mode, nbytes))
        if self.failures:
            raise OSError(self.failures.pop(), "lock contention")


class FakeFcntl:
    LOCK_EX = 2
    LOCK_SH = 1
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def flock(self, fd: int, operation: int) -> None:
        self.calls.append((fd, operation))


def test_windows_uses_msvcrt_exclusive_lock_for_shared_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_msvcrt = FakeMsvcrt()
    fake_fcntl = FakeFcntl()
    monkeypatch.setattr(locks.os, "name", "nt")
    monkeypatch.setattr(locks, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(locks, "fcntl", fake_fcntl)

    lock = locks.AdvisoryLock(tmp_path / "project.lock", exclusive=False)
    lock.acquire()
    lock.release()

    assert [call[1:] for call in fake_msvcrt.calls] == [
        (fake_msvcrt.LK_NBLCK, 1),
        (fake_msvcrt.LK_UNLCK, 1),
    ]
    assert fake_fcntl.calls == []


def test_windows_retries_contention_before_acquiring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_msvcrt = FakeMsvcrt([errno.EACCES, errno.EAGAIN])
    sleeps: list[float] = []
    monkeypatch.setattr(locks.os, "name", "nt")
    monkeypatch.setattr(locks, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(locks.time, "sleep", sleeps.append)

    with locks.AdvisoryLock(tmp_path / "project.lock", exclusive=True):
        pass

    assert [call[1] for call in fake_msvcrt.calls] == [
        fake_msvcrt.LK_NBLCK,
        fake_msvcrt.LK_NBLCK,
        fake_msvcrt.LK_NBLCK,
        fake_msvcrt.LK_UNLCK,
    ]
    assert sleeps == [0.05, 0.05]


def test_windows_contention_times_out_with_structured_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_msvcrt = FakeMsvcrt([errno.EACCES, errno.EACCES])
    monotonic_values = iter([10.0, 10.0, 10.031])
    monkeypatch.setattr(locks.os, "name", "nt")
    monkeypatch.setattr(locks, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(locks.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(locks.time, "sleep", lambda _: None)

    with pytest.raises(DataStoreError) as exc_info:
        locks.AdvisoryLock(
            tmp_path / "project.lock", exclusive=False, timeout_ms=30
        ).acquire()

    assert exc_info.value.details == {
        "path": str(tmp_path / "project.lock"),
        "exclusive": False,
        "timeout_ms": 30,
    }


def test_windows_propagates_non_contention_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_msvcrt = FakeMsvcrt([errno.EIO])
    monkeypatch.setattr(locks.os, "name", "nt")
    monkeypatch.setattr(locks, "msvcrt", fake_msvcrt)

    with pytest.raises(OSError) as exc_info:
        locks.AdvisoryLock(tmp_path / "project.lock", exclusive=True).acquire()

    assert exc_info.value.errno == errno.EIO
    assert len(fake_msvcrt.calls) == 1


def test_windows_without_msvcrt_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(locks.os, "name", "nt")
    monkeypatch.setattr(locks, "msvcrt", None)

    with pytest.raises(DataStoreError) as exc_info:
        locks.AdvisoryLock(tmp_path / "project.lock", exclusive=True).acquire()

    assert exc_info.value.details["capability"] == "msvcrt.locking"
    assert not (tmp_path / "project.lock").exists()


def test_posix_keeps_fcntl_shared_lock_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_fcntl = FakeFcntl()
    fake_msvcrt = FakeMsvcrt()
    monkeypatch.setattr(locks.os, "name", "posix")
    monkeypatch.setattr(locks, "fcntl", fake_fcntl)
    monkeypatch.setattr(locks, "msvcrt", fake_msvcrt)

    with locks.AdvisoryLock(tmp_path / "project.lock", exclusive=False):
        pass

    assert [call[1] for call in fake_fcntl.calls] == [
        fake_fcntl.LOCK_SH | fake_fcntl.LOCK_NB,
        fake_fcntl.LOCK_UN,
    ]
    assert fake_msvcrt.calls == []


def test_non_windows_without_fcntl_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(locks.os, "name", "posix")
    monkeypatch.setattr(locks, "fcntl", None)

    with pytest.raises(DataStoreError) as exc_info:
        locks.AdvisoryLock(tmp_path / "project.lock", exclusive=True).acquire()

    assert exc_info.value.details["capability"] == "fcntl.flock"
    assert not (tmp_path / "project.lock").exists()
