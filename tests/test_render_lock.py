from __future__ import annotations

import contextlib
import io
import json
import multiprocessing
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
