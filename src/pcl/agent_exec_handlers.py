from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TextIO

from .agent_exec import (
    AgentExecStore,
    diagnostic_tail,
    render_metadata,
    run_agent_command,
)
from .errors import InvalidInputError


def handle_agent_exec_command(
    args: argparse.Namespace,
    *,
    cwd: Path,
    json_output: bool,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int | None:
    if args.command != "exec":
        return None
    del error
    tokens = list(args.exec_args)
    store = AgentExecStore.from_override(args.state_dir)
    if tokens and tokens[0] == "--":
        payload, exit_code, lines = run_agent_command(
            tokens[1:],
            cwd=cwd,
            store=store,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            redaction_patterns=args.redact_pattern,
            allowed_env_names=args.allow_env,
        )
        if json_output:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
        else:
            for line in lines:
                print(line, file=output)
        return exit_code
    if not tokens:
        raise InvalidInputError(
            "Use `pcl exec -- <command>`, `pcl exec show <run-id>`, "
            "`pcl exec meta <run-id>`, or `pcl exec gc`."
        )
    action = tokens.pop(0)
    if action == "show":
        return _handle_show(tokens, store=store, json_output=json_output, output=output)
    if action == "meta":
        return _handle_meta(tokens, store=store, json_output=json_output, output=output)
    if action == "gc":
        return _handle_gc(tokens, store=store, json_output=json_output, output=output)
    raise InvalidInputError(
        "Direct commands require the `--` separator.",
        details={"suggested": "pcl exec -- <command>"},
    )


def _handle_show(
    tokens: list[str],
    *,
    store: AgentExecStore,
    json_output: bool,
    output: TextIO,
) -> int:
    if not tokens:
        raise InvalidInputError("`pcl exec show` requires a run id.")
    run_id = tokens.pop(0)
    tail_lines: int | None = None
    errors_mode = False
    while tokens:
        token = tokens.pop(0)
        if token == "--errors":
            errors_mode = True
            continue
        if token == "--tail" and tokens:
            try:
                tail_lines = int(tokens.pop(0))
            except ValueError as exc:
                raise InvalidInputError("--tail requires an integer.") from exc
            continue
        raise InvalidInputError(
            "Unknown `pcl exec show` argument.", details={"argument": token}
        )
    if errors_mode and tail_lines is not None:
        raise InvalidInputError("Choose either --errors or --tail, not both.")
    text = store.read_diagnostic(run_id)
    if tail_lines is not None:
        text = diagnostic_tail(text, tail_lines)
    payload = {
        "ok": True,
        "schema": "agent-exec-diagnostic/v1",
        "run_id": run_id,
        "mode": "tail" if tail_lines is not None else "errors",
        "lines": text.splitlines(),
    }
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
    else:
        print(text, file=output)
    return 0


def _handle_meta(
    tokens: list[str],
    *,
    store: AgentExecStore,
    json_output: bool,
    output: TextIO,
) -> int:
    if len(tokens) != 1:
        raise InvalidInputError("`pcl exec meta` requires exactly one run id.")
    payload = store.read_metadata(tokens[0])
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
    else:
        print(render_metadata(payload), file=output)
    return 0


def _handle_gc(
    tokens: list[str],
    *,
    store: AgentExecStore,
    json_output: bool,
    output: TextIO,
) -> int:
    dry_run = False
    while tokens:
        token = tokens.pop(0)
        if token == "--dry-run":
            dry_run = True
            continue
        raise InvalidInputError(
            "Unknown `pcl exec gc` argument.", details={"argument": token}
        )
    payload = store.collect_garbage(dry_run=dry_run)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)
    else:
        verb = "would remove" if dry_run else "removed"
        print(
            f"agent-exec gc {verb} {payload['selected_count']} runs "
            f"({payload['selected_bytes']} bytes)",
            file=output,
        )
        for failure in payload["failures"]:
            print(f"FAILED {failure['run_id']}: {failure['error']}", file=output)
    return 0 if payload["ok"] else 1
