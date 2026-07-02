from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from pcl.cli import main as pcl_main
from pcl.mcp_server import (
    APPROVAL_LOCAL_RENDER,
    APPROVAL_READ_ONLY,
    ProjectLoopMcpServer,
    encode_message,
    read_message,
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


def test_mcp_message_framing_round_trip() -> None:
    message = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    encoded = encode_message(message)
    decoded = read_message(BytesIO(encoded))

    assert decoded == message
    assert encoded.startswith(b"Content-Length: ")
    body = encoded.split(b"\r\n\r\n", 1)[1]
    assert json.loads(body.decode("utf-8")) == message


def test_mcp_unknown_tool_returns_json_rpc_error(tmp_path: Path) -> None:
    _init_project(tmp_path)
    server = _server(tmp_path)

    response = server.handle(_tool_call("delete_everything"))

    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "Unknown tool: delete_everything"
