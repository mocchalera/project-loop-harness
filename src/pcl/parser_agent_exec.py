from __future__ import annotations

import argparse

from .agent_exec import DEFAULT_CAPTURE_BYTES, DEFAULT_TIMEOUT_SECONDS


def add_agent_exec_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "exec",
        help="Run one non-interactive command with bounded agent-facing output",
        description=(
            "Run a direct argv command without requiring pcl init. Use `pcl exec -- <command>`; "
            "inspect retained sanitized diagnostics with `pcl exec show` or `meta`."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Execution timeout. Defaults to {DEFAULT_TIMEOUT_SECONDS} seconds.",
    )
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=DEFAULT_CAPTURE_BYTES,
        help=(
            "Maximum retained bytes per stdout/stderr stream before bounded head/tail "
            f"capture. Defaults to {DEFAULT_CAPTURE_BYTES}."
        ),
    )
    parser.add_argument(
        "--redact-pattern",
        action="append",
        default=[],
        help="Additional Python regex applied before diagnostic output is stored. Repeatable.",
    )
    parser.add_argument(
        "--allow-env",
        action="append",
        default=[],
        metavar="NAME",
        help="Explicitly inherit an additional environment variable by name. Repeatable.",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override the local agent-exec state directory.",
    )
    parser.add_argument(
        "exec_args",
        nargs=argparse.REMAINDER,
        help=(
            "`-- <argv...>` to run, or `show <run-id>`, `meta <run-id>`, "
            "and `gc [--dry-run]`."
        ),
    )
