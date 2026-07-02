from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO

from . import __version__
from .commands import loop_status, next_action
from .db import connect
from .errors import PclError
from .paths import ProjectPaths, resolve_paths
from .renderer import render_dashboard
from .validators import validate_project


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "pcl-mcp"
APPROVAL_READ_ONLY = "read-only"
APPROVAL_LOCAL_RENDER = "local-render"
REDACTED_SECRET = "[REDACTED_SECRET]"

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
]
_KEY_VALUE_SECRET = re.compile(
    r"\b(api[_-]?key|token|secret|password|private[_-]?key)\b(\s*[:=]\s*)(['\"]?)([^'\"\s,}]{8,})(['\"]?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class JsonRpcError(Exception):
    code: int
    message: str
    data: Any = None


class ProjectLoopMcpServer:
    def __init__(self, paths: ProjectPaths, *, approval_mode: str = APPROVAL_READ_ONLY) -> None:
        self.paths = paths
        self.approval_mode = approval_mode

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            self._handle_notification(method)
            return None
        try:
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
        if method in {"notifications/initialized", "initialized"}:
            return

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
        protocol_version = str(requested or PROTOCOL_VERSION)
        return {
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
    if isinstance(value, dict):
        return {
            key: REDACTED_SECRET if _is_secret_key(key) and item is not None else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(marker in normalized for marker in ("secret", "password", "apikey", "token", "privatekey"))


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED_SECRET, redacted)
    return _KEY_VALUE_SECRET.sub(_redact_key_value_secret, redacted)


def _redact_key_value_secret(match: re.Match[str]) -> str:
    quote = match.group(3)
    closing_quote = match.group(5) if quote else ""
    return f"{match.group(1)}{match.group(2)}{quote}{REDACTED_SECRET}{closing_quote}"


def encode_message(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        raise JsonRpcError(-32700, "Missing Content-Length header.")
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def serve_stdio(server: ProjectLoopMcpServer, *, stdin: BinaryIO, stdout: BinaryIO) -> None:
    while True:
        request = read_message(stdin)
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
    serve_stdio(server, stdin=sys.stdin.buffer, stdout=sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
