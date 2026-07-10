from __future__ import annotations

import asyncio
from importlib.metadata import version
from importlib.util import find_spec
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

import pytest


FIXTURES = Path(__file__).with_name("fixtures")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
OFFICIAL_SDK_VERSION = "1.28.1"


def _request(method: str, params: Any = None, request_id: int = 1) -> dict[str, Any]:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def test_independent_process_client_matches_redacted_wire_fixture(process_client) -> None:
    messages = [
        _request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pcl-conformance-fixture", "version": "1"},
            },
        ),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        _request("tools/list", {}, request_id=2),
        _request(
            "tools/call",
            {"name": "list_features", "arguments": {}},
            request_id=3,
        ),
    ]

    exchange = process_client.exchange(messages)

    expected = json.loads((FIXTURES / "wire-transcript.json").read_text(encoding="utf-8"))
    assert exchange.completed.returncode == 0
    assert exchange.completed.stderr == b""
    assert exchange.transcript == expected
    assert exchange.responses[-1]["result"]["structuredContent"] == {"features": []}
    assert str(process_client.root) not in json.dumps(exchange.transcript, ensure_ascii=False)


@pytest.mark.parametrize(
    ("case_name", "message"),
    [
        ("invalid_params", _request("tools/list", [], request_id=10)),
        ("unknown_method", _request("unsupported/method", {}, request_id=11)),
        (
            "protocol_error",
            _request(
                "tools/call",
                {"name": "list_features", "arguments": {"root": "/not-allowed"}},
                request_id=12,
            ),
        ),
        (
            "domain_error",
            _request(
                "tools/call",
                {"name": "render_dashboard", "arguments": {}},
                request_id=13,
            ),
        ),
    ],
)
def test_protocol_negative_matrix(process_client, case_name: str, message: dict[str, Any]) -> None:
    expected = json.loads((FIXTURES / "negative-matrix.json").read_text(encoding="utf-8"))

    exchange = process_client.exchange(
        [
            _request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "negative-matrix", "version": "1"},
                },
                request_id=1,
            ),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            message,
        ]
    )

    assert exchange.completed.returncode == 0
    assert exchange.responses[-1] == {
        "jsonrpc": "2.0",
        "id": message["id"],
        **expected[case_name],
    }


def test_pre_initialize_tool_call_returns_lifecycle_error(process_client) -> None:
    exchange = process_client.exchange([_request("tools/list", {}, request_id=14)])

    assert exchange.responses == [
        {
            "jsonrpc": "2.0",
            "id": 14,
            "error": {"code": -32002, "message": "Server is not initialized."},
        }
    ]


def test_tools_require_initialized_notification_after_initialize(process_client) -> None:
    exchange = process_client.exchange(
        [
            _request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "lifecycle-matrix", "version": "1"},
                },
                request_id=20,
            ),
            _request("tools/list", {}, request_id=21),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _request("tools/list", {}, request_id=22),
        ]
    )

    assert exchange.completed.returncode == 0
    assert exchange.responses[1] == {
        "jsonrpc": "2.0",
        "id": 21,
        "error": {"code": -32002, "message": "Server is not initialized."},
    }
    assert "result" in exchange.responses[2]


def test_special_character_root_stdin_eof_and_debug_stdout_discipline(process_client) -> None:
    process_client.extra_env.update(
        {
            "PCL_LOG_LEVEL": "DEBUG",
            "PYTHONDEVMODE": "1",
        }
    )
    exchange = process_client.exchange(
        [
            _request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "path-stdin-smoke", "version": "1"},
                },
            ),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _request("tools/list", {}, request_id=2),
        ]
    )

    assert exchange.completed.returncode == 0
    assert len(exchange.responses) == 2
    assert exchange.completed.stderr == b""
    assert all(line.startswith(b'{"jsonrpc":"2.0",') for line in exchange.completed.stdout.splitlines())


def test_official_mcp_python_sdk_process_conformance(initialized_project: Path) -> None:
    if find_spec("mcp") is None:
        pytest.skip(
            "official MCP Python SDK unavailable; install the mcp-test extra (mcp==1.28.1)"
        )

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        pytest.skip(f"official MCP Python SDK import failed; install the mcp-test extra: {exc}")

    assert version("mcp") == OFFICIAL_SDK_VERSION
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SOURCE_ROOT)
        if not existing_pythonpath
        else os.pathsep.join((str(SOURCE_ROOT), existing_pythonpath))
    )

    async def smoke() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "pcl.mcp_server",
                "--stdio",
                "--root",
                str(initialized_project),
            ],
            env=env,
            cwd=REPOSITORY_ROOT,
        )
        async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                called = await session.call_tool("list_features", arguments={})

                assert initialized.protocolVersion == "2025-06-18"
                assert initialized.serverInfo.name == "pcl-mcp"
                assert [tool.name for tool in tools.tools] == [
                    "get_status",
                    "list_features",
                    "list_defects",
                    "list_escalations",
                ]
                assert called.isError is False
                assert called.structuredContent == {"features": []}

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        asyncio.run(smoke())
        stderr.seek(0)
        assert stderr.read() == ""
