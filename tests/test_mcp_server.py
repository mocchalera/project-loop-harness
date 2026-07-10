from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pcl.cli import main as pcl_main
from pcl.mcp_server import (
    APPROVAL_LOCAL_RENDER,
    APPROVAL_READ_ONLY,
    MAX_STDIO_MESSAGE_BYTES,
    ProjectLoopMcpServer,
    SUPPORTED_PROTOCOL_VERSIONS,
    JsonRpcError,
    encode_message,
    read_message,
    serve_stdio,
)
from pcl.paths import resolve_paths


def _server(root: Path, approval_mode: str = APPROVAL_READ_ONLY) -> ProjectLoopMcpServer:
    return ProjectLoopMcpServer(resolve_paths(root), approval_mode=approval_mode)


def _request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def _tool_call(name: str, arguments: dict | None = None, request_id: int = 1) -> dict:
    return _request("tools/call", {"name": name, "arguments": arguments or {}}, request_id)


def _tool_payload(response: dict) -> dict:
    return response["result"]["structuredContent"]


def _init_project(root: Path) -> None:
    assert pcl_main(["init", "--target", str(root)]) == 0


def test_mcp_initialize_and_tool_listing_read_only(tmp_path: Path) -> None:
    _init_project(tmp_path)
    server = _server(tmp_path)

    init = server.handle(_request("initialize", {"protocolVersion": "2025-06-18"}))
    assert init["result"]["serverInfo"]["name"] == "pcl-mcp"
    assert init["result"]["capabilities"] == {"tools": {}}

    tools = server.handle(_request("tools/list"))
    names = [tool["name"] for tool in tools["result"]["tools"]]
    assert names == ["get_status", "list_features", "list_defects", "list_escalations"]
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools["result"]["tools"])


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("2025-06-18", "2025-06-18"),
        ("2025-03-26", "2025-06-18"),
        ("unsupported-version", "2025-06-18"),
        (None, "2025-06-18"),
    ],
)
def test_mcp_initialize_negotiates_supported_protocol_version(
    tmp_path: Path, requested: str | None, expected: str
) -> None:
    _init_project(tmp_path)
    server = _server(tmp_path)

    response = server.handle(_request("initialize", {"protocolVersion": requested}))

    assert SUPPORTED_PROTOCOL_VERSIONS == ("2025-06-18",)
    assert response["result"]["protocolVersion"] == expected


def test_mcp_read_tools_return_project_state(tmp_path: Path) -> None:
    _init_project(tmp_path)
    assert pcl_main(["--root", str(tmp_path), "feature", "add", "--name", "Login", "--surface", "ui:/login"]) == 0
    assert pcl_main([
        "--root",
        str(tmp_path),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Login succeeds",
        "--actual",
        "Blank page",
    ]) == 0
    server = _server(tmp_path)

    status = _tool_payload(server.handle(_tool_call("get_status")))
    assert status["root"] == str(tmp_path)
    assert status["approval_mode"] == "read-only"
    assert status["validation"] == {"errors": [], "ok": True, "warnings": []}
    assert status["status"]["open_defects"][0]["id"] == "D-0001"

    features = _tool_payload(server.handle(_tool_call("list_features")))
    assert features["features"][0]["name"] == "Login"

    defects = _tool_payload(server.handle(_tool_call("list_defects")))
    assert defects["defects"][0]["actual"] == "Blank page"

    escalations = _tool_payload(server.handle(_tool_call("list_escalations")))
    assert escalations == {"escalations": []}


def test_mcp_tool_results_redact_secret_like_values(tmp_path: Path) -> None:
    _init_project(tmp_path)
    api_secret = "super" + "secret" + "value123"
    provider_secret = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz123456"
    password_secret = "hunter2" + "secret"
    assert pcl_main([
        "--root",
        str(tmp_path),
        "feature",
        "add",
        "--name",
        "API setup",
        "--surface",
        "config:local",
        "--description",
        f"Use {'api' + '_key'}={api_secret} and {provider_secret}",
    ]) == 0
    assert pcl_main([
        "--root",
        str(tmp_path),
        "defect",
        "open",
        "--feature",
        "F-0001",
        "--severity",
        "high",
        "--expected",
        "Secret is hidden",
        "--actual",
        f"{'pass' + 'word'}={password_secret}",
    ]) == 0
    server = _server(tmp_path)

    features = server.handle(_tool_call("list_features"))["result"]
    defects = server.handle(_tool_call("list_defects"))["result"]
    status = server.handle(_tool_call("get_status"))["result"]

    rendered = json.dumps([features, defects, status], ensure_ascii=False)
    assert api_secret not in rendered
    assert provider_secret not in rendered
    assert password_secret not in rendered
    assert "[REDACTED_SECRET]" in rendered


def test_mcp_render_dashboard_requires_explicit_approval_mode(tmp_path: Path) -> None:
    _init_project(tmp_path)

    read_only = _server(tmp_path)
    read_only_tools = read_only.handle(_request("tools/list"))["result"]["tools"]
    assert "render_dashboard" not in [tool["name"] for tool in read_only_tools]
    denied = read_only.handle(_tool_call("render_dashboard"))
    assert denied["error"]["code"] == -32000
    assert "local-render" in denied["error"]["message"]

    writable = _server(tmp_path, approval_mode=APPROVAL_LOCAL_RENDER)
    writable_tools = writable.handle(_request("tools/list"))["result"]["tools"]
    render_tool = [tool for tool in writable_tools if tool["name"] == "render_dashboard"][0]
    assert render_tool["annotations"]["readOnlyHint"] is False

    rendered = _tool_payload(writable.handle(_tool_call("render_dashboard")))
    assert rendered == {
        "data_path": str(tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json"),
        "machine_context": (
            "Use data_path or read-only MCP tools for state. "
            "dashboard.html is human-only and intentionally not returned."
        ),
        "rendered": True,
    }
    assert rendered["rendered"] is True
    assert "dashboard" not in rendered
    assert str(tmp_path / ".project-loop" / "dashboard" / "dashboard.html") not in json.dumps(rendered)
    assert (tmp_path / ".project-loop" / "dashboard" / "dashboard.html").exists()
    assert (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").exists()


def test_mcp_tools_reject_arguments_to_preserve_root_boundary(tmp_path: Path) -> None:
    _init_project(tmp_path)
    server = _server(tmp_path)

    response = server.handle(_tool_call("list_features", {"root": "/tmp/other"}))

    assert response["error"]["code"] == -32602
    assert "server root is fixed" in response["error"]["message"]


def test_mcp_rejects_non_object_params(tmp_path: Path) -> None:
    _init_project(tmp_path)
    server = _server(tmp_path)

    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []})

    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "Params must be an object."


@pytest.mark.parametrize("line_ending", [b"\n", b"\r\n"])
def test_mcp_message_framing_round_trip_lf_and_crlf(line_ending: bytes) -> None:
    message = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"text": "a\nb"}}

    encoded = encode_message(message)
    decoded = read_message(BytesIO(encoded[:-1] + line_ending))

    assert decoded == message
    assert encoded.endswith(b"\n")
    assert encoded.count(b"\n") == 1
    assert b"Content-Length" not in encoded
    assert json.loads(encoded.decode("utf-8")) == message


def test_mcp_message_reader_handles_clean_eof_and_rejects_partial_eof() -> None:
    message = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    encoded = encode_message(message)

    stream = BytesIO(encoded)
    assert read_message(stream) == message
    assert read_message(stream) is None
    with pytest.raises(JsonRpcError, match="ended before newline delimiter") as partial:
        read_message(BytesIO(encoded.rstrip(b"\n")))
    assert partial.value.code == -32700


def test_mcp_message_reader_rejects_malformed_json_and_empty_line() -> None:
    with pytest.raises(JsonRpcError, match="Invalid JSON-RPC message") as malformed:
        read_message(BytesIO(b'{"jsonrpc":"2.0",bad}\n'))
    assert malformed.value.code == -32700

    with pytest.raises(JsonRpcError, match="Empty JSON-RPC message line") as empty:
        read_message(BytesIO(b"\r\n"))
    assert empty.value.code == -32700

    with pytest.raises(JsonRpcError, match="Invalid JSON-RPC message") as legacy:
        read_message(BytesIO(b"Content-Length: 2\r\n"))
    assert legacy.value.code == -32700


def test_mcp_message_reader_rejects_oversized_line_and_recovers_boundary() -> None:
    following = encode_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    stream = BytesIO(b"x" * (MAX_STDIO_MESSAGE_BYTES + 1) + b"\n" + following)

    with pytest.raises(JsonRpcError, match="exceeds maximum line size") as oversized:
        read_message(stream)
    assert oversized.value.code == -32700
    assert read_message(stream)["id"] == 2


def test_mcp_stdio_reports_parse_error_without_corrupting_protocol_channel(tmp_path: Path) -> None:
    _init_project(tmp_path)
    stdout = BytesIO()
    stderr = BytesIO()
    requests = b"not-json\n" + encode_message(_request("ping", request_id=2))

    serve_stdio(_server(tmp_path), stdin=BytesIO(requests), stdout=stdout, stderr=stderr)

    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert messages == [
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Invalid JSON-RPC message."},
        },
        {"jsonrpc": "2.0", "id": 2, "result": {}},
    ]
    assert b"Invalid JSON-RPC message" in stderr.getvalue()


def test_mcp_notification_has_no_response(tmp_path: Path) -> None:
    _init_project(tmp_path)
    stdout = BytesIO()
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    serve_stdio(_server(tmp_path), stdin=BytesIO(encode_message(notification)), stdout=stdout)

    assert stdout.getvalue() == b""


def test_mcp_process_initialize_list_and_call_has_pure_stdout(tmp_path: Path) -> None:
    _init_project(tmp_path)
    requests = [
        _request("initialize", {"protocolVersion": "unsupported-version"}, request_id=1),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        _request("tools/list", request_id=2),
        _tool_call("list_features", request_id=3),
    ]
    wire_input = b"".join(encode_message(message) for message in requests)
    env = os.environ.copy()
    source_root = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = str(source_root)

    completed = subprocess.run(
        [sys.executable, "-m", "pcl.mcp_server", "--stdio", "--root", str(tmp_path)],
        input=wire_input,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0
    stdout_lines = completed.stdout.splitlines()
    assert len(stdout_lines) == 3
    responses = [json.loads(line) for line in stdout_lines]
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert [tool["name"] for tool in responses[1]["result"]["tools"]] == [
        "get_status",
        "list_features",
        "list_defects",
        "list_escalations",
    ]
    assert responses[2]["result"]["structuredContent"] == {"features": []}
    assert all(line.startswith(b'{"jsonrpc":"2.0",') for line in stdout_lines)
    assert completed.stderr == b""


def test_mcp_unknown_tool_returns_json_rpc_error(tmp_path: Path) -> None:
    _init_project(tmp_path)
    server = _server(tmp_path)

    response = server.handle(_tool_call("delete_everything"))

    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "Unknown tool: delete_everything"
