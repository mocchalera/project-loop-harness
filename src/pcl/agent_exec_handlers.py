from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from .agent_exec import (
    gc_agent_exec,
    read_agent_exec_diagnostic,
    read_agent_exec_meta,
    run_agent_exec,
)
from .errors import InvalidInputError
from .parser_agent_exec import AGENT_EXEC_ARGV_SENTINEL
from .paths import ProjectPaths


def handle_agent_exec_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int | None:
    if args.command != "exec":
        return None
    tokens = list(args.exec_args)
    if not tokens:
        raise InvalidInputError(
            "Use `pcl exec -- <argv...>`, `pcl exec show`, `pcl exec meta`, or `pcl exec gc`."
        )

    if tokens[0] == AGENT_EXEC_ARGV_SENTINEL:
        outcome = run_agent_exec(
            tokens[1:],
            cwd=paths.root,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            redaction_patterns=args.redact_pattern,
            allowed_env_names=args.allow_env,
        )
        if json_output:
            _write_json(outcome.result, output)
        else:
            print(outcome.presentation, file=output)
        return outcome.process_exit_code

    operation = tokens[0]
    if operation == "show":
        run_id, tail_lines = _parse_show(tokens[1:])
        text = read_agent_exec_diagnostic(run_id, tail_lines=tail_lines)
        if json_output:
            _write_json(
                {
                    "schema": "agent-exec-diagnostic-view/v1",
                    "ok": True,
                    "run_id": run_id,
                    "tail_lines": tail_lines,
                    "text": text,
                },
                output,
            )
        else:
            print(text, file=output)
        return 0

    if operation == "meta":
        if len(tokens) != 2:
            raise InvalidInputError("Use `pcl exec meta <run-id> [--json]`.")
        payload = read_agent_exec_meta(tokens[1])
        if json_output:
            _write_json(payload, output)
        else:
            diagnostics = payload["diagnostics"]
            print(
                f"{payload['status']} run={payload['run_id']} exit={payload['exit_code']} "
                f"duration={payload['duration_ms'] / 1000:.3f}s "
                f"diagnostics={str(diagnostics['available']).lower()}",
                file=output,
            )
        return 0

    if operation == "gc":
        if tokens[1:] not in ([], ["--dry-run"]):
            raise InvalidInputError("Use `pcl exec gc [--dry-run] [--json]`.")
        result = gc_agent_exec(dry_run=tokens[1:] == ["--dry-run"])
        if json_output:
            _write_json(result, output)
        else:
            count = (
                len(result["candidate_run_ids"])
                if result["dry_run"]
                else len(result["removed_run_ids"])
            )
            action = "Would remove" if result["dry_run"] else "Removed"
            print(
                f"{action} {count} agent execution run(s); "
                f"reclaimable={result['reclaimable_bytes']}B",
                file=output,
            )
            for run_id in result["unsafe_run_ids"]:
                print(f"WARNING: skipped unsafe run directory {run_id}", file=error)
        return 0 if result["ok"] else 1

    raise InvalidInputError(
        "Direct execution requires the `--` separator, for example `pcl exec -- npm test`."
    )


def _parse_show(tokens: list[str]) -> tuple[str, int | None]:
    if len(tokens) == 2 and tokens[1] == "--errors":
        return tokens[0], None
    if len(tokens) == 3 and tokens[1] == "--tail":
        try:
            tail_lines = int(tokens[2])
        except ValueError as exc:
            raise InvalidInputError("--tail requires an integer line count.") from exc
        return tokens[0], tail_lines
    raise InvalidInputError(
        "Use `pcl exec show <run-id> --errors` or `pcl exec show <run-id> --tail <n>`."
    )


def _write_json(payload: object, output: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
