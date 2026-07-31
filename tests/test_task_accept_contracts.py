from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcl.mcp_server import (
    APPROVAL_LOCAL_RENDER,
    APPROVAL_READ_ONLY,
    APPROVAL_TASK_ACCEPT_WRITE,
    ProjectLoopMcpServer,
)
from pcl.paths import resolve_paths

from task_accept_helpers import accept_args, prepare_acceptance, run_json


def _request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def _initialize(server: ProjectLoopMcpServer, params: dict | None = None) -> dict:
    response = server.handle(_request("initialize", params or {"protocolVersion": "2025-06-18"}))
    assert response is not None
    if "result" in response:
        assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    return response


def _tool_names(server: ProjectLoopMcpServer) -> list[str]:
    return [tool["name"] for tool in server.handle(_request("tools/list"))["result"]["tools"]]


@pytest.mark.parametrize("mode", [APPROVAL_READ_ONLY, APPROVAL_LOCAL_RENDER])
def test_mcp_default_modes_deny_task_accept_listing_and_dispatch(
    tmp_path: Path,
    capsys,
    mode: str,
) -> None:
    prepare_acceptance(tmp_path, capsys, test_count=1)
    server = ProjectLoopMcpServer(resolve_paths(tmp_path), approval_mode=mode)
    _initialize(server)

    assert "task_accept" not in _tool_names(server)
    denied = server.handle(
        _request(
            "tools/call",
            {"name": "task_accept", "arguments": {"root": "/tmp/other"}},
        )
    )
    assert denied["error"]["code"] == -32003
    assert denied["error"]["data"] == {
        "active_capability": mode,
        "required_capability": APPROVAL_TASK_ACCEPT_WRITE,
        "tool": "task_accept",
    }


def test_mcp_write_mode_uses_cli_service_and_canonical_envelope_bytes(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)
    server = ProjectLoopMcpServer(
        resolve_paths(tmp_path), approval_mode=APPROVAL_TASK_ACCEPT_WRITE
    )
    init = _initialize(server)
    assert init["result"]["capabilities"]["experimental"]["pcl"]["taskAcceptWrite"] is True
    assert _tool_names(server) == [
        "get_status",
        "list_features",
        "list_defects",
        "list_escalations",
        "task_accept",
    ]

    response = server.handle(
        _request(
            "tools/call",
            {
                "name": "task_accept",
                "arguments": {
                    "task_id": fixture["task_id"],
                    "artifact": fixture["artifact"],
                    "command": "pytest -q",
                    "summary": "Acceptance verified",
                    "copy": True,
                    "test_ids": fixture["test_ids"],
                },
            },
        )
    )
    result = response["result"]
    canonical = json.dumps(
        result["structuredContent"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert result["content"] == [{"type": "text", "text": canonical}]
    assert result["isError"] is False


@pytest.mark.parametrize(
    ("segments", "pointer"),
    [
        (("approvalMode",), "/params/approvalMode"),
        (("approval_mode",), "/params/approval_mode"),
        (("capabilities", "pclTaskAcceptWrite"), "/params/capabilities/pclTaskAcceptWrite"),
        (("capabilities", "pcl_task_accept_write"), "/params/capabilities/pcl_task_accept_write"),
        (("capabilities", "taskAccept"), "/params/capabilities/taskAccept"),
        (("capabilities", "task_accept"), "/params/capabilities/task_accept"),
    ],
)
@pytest.mark.parametrize(
    ("pointer_value", "value_type"),
    [
        ("task-accept-write", "string"),
        (True, "boolean"),
        (None, "null"),
        (1, "number"),
        ([], "array"),
        ({}, "object"),
    ],
)
def test_mcp_initialize_cannot_promote_startup_authority(
    tmp_path: Path,
    segments: tuple[str, ...],
    pointer: str,
    pointer_value,
    value_type: str,
) -> None:
    server = ProjectLoopMcpServer(resolve_paths(tmp_path), approval_mode=APPROVAL_READ_ONLY)
    params: dict = {"protocolVersion": "2025-06-18"}
    target = params
    for segment in segments[:-1]:
        target = target.setdefault(segment, {})
    target[segments[-1]] = pointer_value

    response = _initialize(server, params)

    assert response["error"]["code"] == -32003
    assert response["error"]["data"]["attempted_pointers"] == [
        {"pointer": pointer, "value_type": value_type}
    ]


def test_cli_request_hash_is_stable_for_test_order_and_full_length(tmp_path: Path, capsys) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    reversed_fixture = {**fixture, "test_ids": list(reversed(fixture["test_ids"]))}

    accepted = run_json(tmp_path, capsys, *accept_args(reversed_fixture))

    request_id = accepted["identity"]["request_id"]
    assert request_id.startswith("sha256:")
    assert len(request_id) == len("sha256:") + 64
    assert accepted["identity"]["test_ids"] == sorted(fixture["test_ids"])


def test_fresh_and_replay_run_full_strict_exactly_once_and_p0b_is_strict_free(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)
    from pcl import task_accept

    original = task_accept.validate_project
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(task_accept, "validate_project", counted)
    accepted = run_json(tmp_path, capsys, *accept_args(fixture))
    assert accepted["ok"] is True
    assert calls == 1
    calls = 0
    replay = run_json(tmp_path, capsys, *accept_args(fixture))
    assert replay["status"] == "already_accepted"
    assert calls == 1
