from __future__ import annotations

import argparse
from enum import Enum, auto
import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO

from . import __version__
from .commands import loop_status, next_action
from .db import connect
from .errors import PclError
from .paths import ProjectPaths, resolve_paths
from .redaction import REDACTED_SECRET as REDACTED_SECRET
from .redaction import SECRET_PATTERNS, redact_text, redact_value
from .renderer import render_dashboard
from .validators import validate_project


SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18",)
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
MAX_STDIO_MESSAGE_BYTES = 1_048_576
SERVER_NAME = "pcl-mcp"
APPROVAL_READ_ONLY = "read-only"
APPROVAL_LOCAL_RENDER = "local-render"
_SECRET_PATTERNS = SECRET_PATTERNS
_SERVER_NOT_INITIALIZED = -32002


class _InitializationState(Enum):
    NOT_INITIALIZED = auto()
    INITIALIZING = auto()
    INITIALIZED = auto()


@dataclass(frozen=True)
class JsonRpcError(Exception):
    code: int
    message: str
    data: Any = None


class ProjectLoopMcpServer:
    def __init__(self, paths: ProjectPaths, *, approval_mode: str = APPROVAL_READ_ONLY) -> None:
        self.paths = paths
        self.approval_mode = approval_mode
        self._initialization_state = _InitializationState.NOT_INITIALIZED

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            self._handle_notification(method)
            return None
        try:
            self._ensure_request_allowed(method)
            params = message.get("params", {})
            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise JsonRpcError(-32602, "Params must be an object.")
            result = self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except JsonRpcError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.data is not None:
                error["data"] = exc.data
            return {"jsonrpc": "2.0", "id": request_id, "error": error}
        except PclError as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": str(exc),
                    "data": exc.to_dict(),
                },
            }

    def _handle_notification(self, method: Any) -> None:
        if (
            method in {"notifications/initialized", "initialized"}
            and self._initialization_state is _InitializationState.INITIALIZING
        ):
            self._initialization_state = _InitializationState.INITIALIZED

    def _ensure_request_allowed(self, method: Any) -> None:
        if method == "ping":
            return
        if method == "initialize":
            if self._initialization_state is not _InitializationState.NOT_INITIALIZED:
                raise JsonRpcError(-32600, "Server is already initialized.")
            return
        if self._initialization_state is not _InitializationState.INITIALIZED:
            raise JsonRpcError(_SERVER_NOT_INITIALIZED, "Server is not initialized.")

    def _dispatch(self, method: Any, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._tools()}
        if method == "tools/call":
            return self._call_tool(params)
        raise JsonRpcError(-32601, f"Method not found: {method}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        protocol_version = (
            requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        )
        result = {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": (
                "Project Loop Harness MCP exposes safe local pcl read operations. "
                "State mutations still go through the pcl CLI. Generated dashboard HTML "
                "is a human-only view and must not be read or parsed as project state. "
                "render_dashboard is only available when the server is started with "
                "--approval-mode local-render."
            ),
        }
        self._initialization_state = _InitializationState.INITIALIZING
        return result

    def _tools(self) -> list[dict[str, Any]]:
        tools = [
            _tool(
                "get_status",
                "Return loop status, validation result, and next suggested pcl action.",
                read_only=True,
            ),
            _tool("list_features", "List tracked features from the local project-loop database."),
            _tool("list_defects", "List tracked defects from the local project-loop database."),
            _tool("list_escalations", "List escalation queue items from the local project-loop database."),
        ]
        if self.approval_mode == APPROVAL_LOCAL_RENDER:
            tools.append(
                _tool(
                    "render_dashboard",
                    (
                        "Render the local human dashboard and dashboard-data JSON from state. "
                        "Returns machine-oriented dashboard-data metadata only; dashboard HTML is human-only."
                    ),
                    read_only=False,
                )
            )
        return tools

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "Tool arguments must be an object.")
        if arguments:
            raise JsonRpcError(
                -32602,
                "Project Loop Harness MCP tools do not accept arguments; the server root is fixed at startup.",
                {"arguments": sorted(arguments)},
            )
        if name == "get_status":
            return _tool_result(self._get_status())
        if name == "list_features":
            return _tool_result({"features": self._rows("features", _FEATURE_COLUMNS)})
        if name == "list_defects":
            return _tool_result({"defects": self._rows("defects", _DEFECT_COLUMNS)})
        if name == "list_escalations":
            return _tool_result({"escalations": self._rows("escalations", _ESCALATION_COLUMNS)})
        if name == "render_dashboard":
            if self.approval_mode != APPROVAL_LOCAL_RENDER:
                raise JsonRpcError(
                    -32000,
                    "render_dashboard requires --approval-mode local-render.",
                    {"approval_mode": self.approval_mode},
                )
            render_dashboard(self.paths)
            return _tool_result(
                {
                    "data_path": str(self.paths.dashboard_data),
                    "machine_context": (
                        "Use data_path or read-only MCP tools for state. "
                        "dashboard.html is human-only and intentionally not returned."
                    ),
                    "rendered": True,
                }
            )
        raise JsonRpcError(-32602, f"Unknown tool: {name}")

    def _get_status(self) -> dict[str, Any]:
        validation = validate_project(self.paths).to_dict()
        return {
            "root": str(self.paths.root),
            "approval_mode": self.approval_mode,
            "validation": validation,
            "status": loop_status(self.paths),
            "next_action": next_action(self.paths),
        }

    def _rows(self, table: str, columns: list[str]) -> list[dict[str, Any]]:
        sql_columns = ", ".join(columns)
        conn = connect(self.paths.db_path)
        try:
            order = "id"
            if table in {"defects", "escalations"}:
                order = "created_at DESC, id DESC"
            rows = conn.execute(f"SELECT {sql_columns} FROM {table} ORDER BY {order}").fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


_FEATURE_COLUMNS = ["id", "name", "surface", "description", "status", "confidence", "updated_at"]
_DEFECT_COLUMNS = [
    "id",
    "feature_id",
    "test_case_id",
    "severity",
    "expected",
    "actual",
    "status",
    "evidence_id",
    "updated_at",
]
_ESCALATION_COLUMNS = [
    "id",
    "workflow_run_id",
    "severity",
    "question",
    "recommendation",
    "status",
    "created_at",
]


def _tool(name: str, description: str, *, read_only: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": read_only},
    }


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _redact_secrets(payload)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            }
        ],
        "structuredContent": payload,
    }


def _redact_secrets(value: Any) -> Any:
    redacted, _ = redact_value(value)
    return redacted


def _redact_text(value: str) -> str:
    redacted, _ = redact_text(value)
    return redacted


def encode_message(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return body + b"\n"


def read_message(
    stream: BinaryIO, *, max_line_bytes: int = MAX_STDIO_MESSAGE_BYTES
) -> dict[str, Any] | None:
    line = stream.readline(max_line_bytes + 2)
    if line == b"":
        return None
    terminated = line.endswith(b"\n")
    payload = line[:-1] if terminated else line
    if payload.endswith(b"\r"):
        payload = payload[:-1]
    if len(payload) > max_line_bytes:
        _discard_until_newline(stream, line, chunk_size=max_line_bytes + 2)
        raise JsonRpcError(
            -32700,
            f"JSON-RPC message exceeds maximum line size of {max_line_bytes} bytes.",
        )
    if not terminated:
        raise JsonRpcError(-32700, "JSON-RPC message ended before newline delimiter.")
    if not payload:
        raise JsonRpcError(-32700, "Empty JSON-RPC message line.")
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonRpcError(-32700, "Invalid JSON-RPC message.") from exc
    if not isinstance(message, dict):
        raise JsonRpcError(-32600, "JSON-RPC message must be an object.")
    return message


def _discard_until_newline(stream: BinaryIO, initial: bytes, *, chunk_size: int) -> None:
    chunk = initial
    while not chunk.endswith(b"\n"):
        chunk = stream.readline(chunk_size)
        if chunk == b"":
            return


def _error_response(error: JsonRpcError) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        payload["data"] = error.data
    return {"jsonrpc": "2.0", "id": None, "error": payload}


def serve_stdio(
    server: ProjectLoopMcpServer,
    *,
    stdin: BinaryIO,
    stdout: BinaryIO,
    stderr: BinaryIO | None = None,
) -> None:
    while True:
        try:
            request = read_message(stdin)
        except JsonRpcError as exc:
            if stderr is not None:
                stderr.write(f"pcl-mcp stdio: {exc.message}\n".encode("utf-8"))
                stderr.flush()
            stdout.write(encode_message(_error_response(exc)))
            stdout.flush()
            continue
        if request is None:
            return
        response = server.handle(request)
        if response is None:
            continue
        stdout.write(encode_message(response))
        stdout.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcl-mcp", description="Project Loop Harness MCP server")
    parser.add_argument("--stdio", action="store_true", help="Run MCP over stdio.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument(
        "--approval-mode",
        choices=[APPROVAL_READ_ONLY, APPROVAL_LOCAL_RENDER],
        default=APPROVAL_READ_ONLY,
        help="Explicit permission mode. Defaults to read-only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.stdio:
        parser.error("Only --stdio transport is implemented.")
    server = ProjectLoopMcpServer(resolve_paths(args.root), approval_mode=args.approval_mode)
    serve_stdio(
        server,
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
