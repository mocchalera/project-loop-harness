from __future__ import annotations

import contextlib
import io
import json
import multiprocessing
from pathlib import Path
import queue

from pcl.cli import main
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
