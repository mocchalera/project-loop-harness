from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import multiprocessing
import os
from pathlib import Path
import queue

import pytest

from pcl.cli import main
from pcl.errors import DataStoreError
from pcl.locks import AdvisoryLock, project_operation_lock
from pcl.mcp_server import APPROVAL_LOCAL_RENDER, ProjectLoopMcpServer
from pcl.paths import resolve_paths


def _install_lock_probe(attempting) -> None:
    original_acquire = AdvisoryLock.acquire

    def probed_acquire(self) -> None:
        if self.exclusive and self.path.name == "project.lock":
            attempting.set()
        original_acquire(self)

    AdvisoryLock.acquire = probed_acquire


def _cli_render_worker(root: str, attempting, results) -> None:
    _install_lock_probe(attempting)
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
        status = main(["--root", root, "render", "--json"])
    results.put(("cli", status, json.loads(output.getvalue())))


def _mcp_render_worker(root: str, attempting, results) -> None:
    _install_lock_probe(attempting)
    server = ProjectLoopMcpServer(
        resolve_paths(root),
        approval_mode=APPROVAL_LOCAL_RENDER,
    )
    initialized = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    rendered = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "render_dashboard", "arguments": {}},
        }
    )
    results.put(("mcp", initialized, rendered))


def _public_render_worker(root: str, attempting, results) -> None:
    from pcl.renderer import render_dashboard

    _install_lock_probe(attempting)
    try:
        render_dashboard(resolve_paths(root))
    except Exception as exc:  # pragma: no cover - diagnostic process boundary
        results.put(("public", type(exc).__name__, str(exc)))
    else:
        results.put(("public", "ok", None))


def _exclusive_lock_holder(loop_dir: str, acquired, release) -> None:
    with project_operation_lock(Path(loop_dir), exclusive=True):
        acquired.set()
        release.wait(timeout=20)


def test_cli_and_mcp_render_processes_share_direct_exclusive_lock(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    cli_attempting = context.Event()
    mcp_attempting = context.Event()
    cli = context.Process(
        target=_cli_render_worker,
        args=(str(tmp_path), cli_attempting, results),
    )
    mcp = context.Process(
        target=_mcp_render_worker,
        args=(str(tmp_path), mcp_attempting, results),
    )

    with project_operation_lock(tmp_path / ".project-loop", exclusive=True):
        cli.start()
        mcp.start()
        assert cli_attempting.wait(timeout=10)
        assert mcp_attempting.wait(timeout=10)
        assert cli.is_alive()
        assert mcp.is_alive()

    cli.join(timeout=20)
    mcp.join(timeout=20)
    assert cli.exitcode == 0
    assert mcp.exitcode == 0
    received = {}
    for _ in range(2):
        try:
            item = results.get(timeout=5)
        except queue.Empty as exc:  # pragma: no cover - diagnostic guard
            raise AssertionError("render worker did not return a result") from exc
        received[item[0]] = item[1:]
    assert received["cli"][0] == 0
    assert received["cli"][1]["ok"] is True
    assert "result" in received["mcp"][1]
    assert (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").is_file()
    assert (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").is_file()


def test_public_renderer_blocks_on_another_process_exclusive_lock(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    attempting = context.Event()
    worker = context.Process(
        target=_public_render_worker,
        args=(str(tmp_path), attempting, results),
    )

    with project_operation_lock(tmp_path / ".project-loop", exclusive=True):
        worker.start()
        assert attempting.wait(timeout=10)
        assert worker.is_alive()

    worker.join(timeout=20)
    assert worker.exitcode == 0
    assert results.get(timeout=5) == ("public", "ok", None)


def test_lock_held_renderer_requires_live_matching_capability(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.renderer import _render_dashboard_with_lock, render_dashboard

    other_root = tmp_path / "other"
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert main(["init", "--target", str(other_root), "--json"]) == 0
    capsys.readouterr()
    paths = resolve_paths(tmp_path)
    other_paths = resolve_paths(other_root)

    with pytest.raises(TypeError):
        render_dashboard(paths, operation_lock_held=True)

    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        _render_dashboard_with_lock(paths, capability=capability)
        with pytest.raises(DataStoreError):
            _render_dashboard_with_lock(paths, capability=object())
        with pytest.raises(DataStoreError):
            _render_dashboard_with_lock(other_paths, capability=capability)

    with pytest.raises(DataStoreError):
        _render_dashboard_with_lock(paths, capability=capability)


def test_lock_held_renderer_rejects_root_aba_and_replaced_lock_file(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.renderer import _render_dashboard_with_lock

    target = tmp_path / "target"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    replacement_loop = tmp_path / "replacement-loop"
    assert main(["init", "--target", str(target), "--json"]) == 0
    capsys.readouterr()
    assert main(["init", "--target", str(replacement), "--json"]) == 0
    capsys.readouterr()
    paths = resolve_paths(target)
    original_root_identity = os.stat(target, follow_symlinks=False)
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    holder = None

    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        target.rename(displaced)
        replacement.rename(target)
        (target / ".project-loop").rename(replacement_loop)
        (displaced / ".project-loop").rename(target / ".project-loop")
        held_lock_path = target / ".project-loop" / "project.lock"
        held_lock_path.rename(target / ".project-loop" / "project.lock.capability-held")
        holder = context.Process(
            target=_exclusive_lock_holder,
            args=(str(target / ".project-loop"), acquired, release),
        )
        holder.start()
        assert acquired.wait(timeout=10)
        assert holder.is_alive()
        replacement_root_identity = os.stat(target, follow_symlinks=False)
        assert (
            original_root_identity.st_dev,
            original_root_identity.st_ino,
        ) != (
            replacement_root_identity.st_dev,
            replacement_root_identity.st_ino,
        )

        try:
            with pytest.raises(DataStoreError):
                _render_dashboard_with_lock(
                    resolve_paths(target),
                    capability=capability,
                )
        finally:
            release.set()

    assert holder is not None
    holder.join(timeout=20)
    assert holder.exitcode == 0


def test_lock_held_renderer_accepts_same_root_identity_after_rename(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.renderer import _render_dashboard_with_lock

    original = tmp_path / "original"
    renamed = tmp_path / "renamed"
    assert main(["init", "--target", str(original), "--json"]) == 0
    capsys.readouterr()
    paths = resolve_paths(original)

    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        original.rename(renamed)
        _render_dashboard_with_lock(
            resolve_paths(renamed),
            capability=capability,
        )

    assert (renamed / ".project-loop" / "dashboard" / "dashboard.html").is_file()


def test_private_capability_constructor_cannot_forge_live_ownership(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.locks import _ExclusiveProjectOperationCapability
    from pcl.renderer import _render_dashboard_with_lock

    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    paths = resolve_paths(tmp_path)

    with AdvisoryLock(
        paths.loop_dir / "project.lock",
        exclusive=True,
    ) as lock:
        capability = lock._capability
        assert capability is not None
        loop_stat = os.stat(paths.loop_dir, follow_symlinks=True)
        try:
            forged = _ExclusiveProjectOperationCapability(
                lock,
                loop_identity=(
                    loop_stat.st_dev,
                    loop_stat.st_ino,
                    loop_stat.st_mode & 0o170000,
                ),
            )
        except TypeError:
            return
        lock._capability = forged
        with pytest.raises(DataStoreError):
            _render_dashboard_with_lock(paths, capability=forged)


def test_reacquired_lock_rejects_reused_expired_capability(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.renderer import _render_dashboard_with_lock

    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    paths = resolve_paths(tmp_path)

    with project_operation_lock(paths.loop_dir, exclusive=True) as expired:
        assert expired is not None
    with project_operation_lock(paths.loop_dir, exclusive=True) as current:
        with pytest.raises(DataStoreError):
            _render_dashboard_with_lock(paths, capability=expired)
        _render_dashboard_with_lock(paths, capability=current)


def test_lock_held_renderer_rejects_capability_from_non_owner_thread(
    tmp_path: Path,
    capsys,
) -> None:
    from pcl.renderer import _render_dashboard_with_lock

    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    paths = resolve_paths(tmp_path)

    def render_from_another_thread(capability):
        try:
            _render_dashboard_with_lock(paths, capability=capability)
        except Exception as exc:
            return exc
        return None

    with project_operation_lock(paths.loop_dir, exclusive=True) as capability:
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(
                render_from_another_thread,
                capability,
            ).result(timeout=10)

    assert isinstance(result, DataStoreError)
