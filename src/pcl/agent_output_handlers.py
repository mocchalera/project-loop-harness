from __future__ import annotations

import argparse
import json
from typing import TextIO

from .agent_output_policy import (
    canonical_agent_output_policy,
    classify_agent_output_argv_json,
)
from .agent_output_renderer import render_agent_output_host
from .paths import ProjectPaths


def handle_agent_output_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    output: TextIO,
) -> int | None:
    del paths
    if args.command != "agent-output":
        return None

    if args.agent_output_command == "policy":
        payload = canonical_agent_output_policy()
        if json_output:
            _write_json(payload, output)
        else:
            output.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return 0

    if args.agent_output_command == "classify":
        payload = classify_agent_output_argv_json(args.argv_json)
        if json_output:
            _write_json(payload, output)
        else:
            output.write(
                f"{payload['classification']} reason={payload['reason_code']} "
                f"may_rewrite={str(payload['may_rewrite']).lower()}\n"
            )
        return 0

    if args.agent_output_command == "render":
        content = render_agent_output_host(args.host)
        if json_output:
            _write_json(
                {
                    "schema": "agent-output-render/v1",
                    "host": args.host,
                    "content": content,
                },
                output,
            )
        else:
            output.write(content)
        return 0

    raise ValueError(f"Unsupported agent-output command: {args.agent_output_command}")


def _write_json(payload: object, output: TextIO) -> None:
    output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
