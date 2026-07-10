from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from pcl.cli import main as pcl_main


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"


@dataclass(frozen=True)
class Exchange:
    completed: subprocess.CompletedProcess[bytes]
    responses: list[dict[str, Any]]
    transcript: list[dict[str, Any]]


class ProcessConformanceClient:
    """Independent newline-delimited JSON-RPC client for process-level fixtures."""

    def __init__(self, root: Path, *, extra_env: dict[str, str] | None = None) -> None:
        self.root = root
        self.extra_env = extra_env or {}

    def exchange(self, messages: list[dict[str, Any]]) -> Exchange:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(SOURCE_ROOT)
            if not existing_pythonpath
            else os.pathsep.join((str(SOURCE_ROOT), existing_pythonpath))
        )
        env.update(self.extra_env)
        wire_input = b"".join(_encode(message) for message in messages)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pcl.mcp_server",
                "--stdio",
                "--root",
                str(self.root),
            ],
            input=wire_input,
            capture_output=True,
            check=False,
            env=env,
            cwd=Path(__file__).resolve().parents[2],
        )
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        transcript = _pair_transcript(messages, responses)
        return Exchange(completed=completed, responses=responses, transcript=transcript)


def _encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"


def _pair_transcript(
    messages: list[dict[str, Any]], responses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    responses_by_id = {response.get("id"): response for response in responses}
    transcript: list[dict[str, Any]] = []
    for message in messages:
        transcript.append({"direction": "client->server", "message": message})
        if "id" in message:
            transcript.append(
                {"direction": "server->client", "message": responses_by_id[message["id"]]}
            )
    return transcript


@pytest.fixture
def initialized_project(tmp_path: Path) -> Path:
    root = tmp_path / "MCP conformance 日本語"
    root.mkdir()
    assert pcl_main(["init", "--target", str(root)]) == 0
    return root


@pytest.fixture
def process_client(initialized_project: Path) -> ProcessConformanceClient:
    return ProcessConformanceClient(initialized_project)
