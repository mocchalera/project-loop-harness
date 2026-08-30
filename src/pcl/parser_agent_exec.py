from __future__ import annotations

import argparse


AGENT_EXEC_ARGV_SENTINEL = "__PCL_AGENT_EXEC_ARGV__"
DEFAULT_AGENT_EXEC_TIMEOUT_SECONDS = 120
DEFAULT_AGENT_EXEC_MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def add_agent_exec_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "exec",
        help="Run one argv command with bounded agent-facing output and local diagnostics",
        description=(
            "Run a non-interactive command without requiring pcl init. Use `--` before "
            "the child argv. Inspect retained failure diagnostics with `pcl exec show`."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_AGENT_EXEC_TIMEOUT_SECONDS,
        help="Terminate the child process group after this many seconds (default: 120).",
    )
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=DEFAULT_AGENT_EXEC_MAX_OUTPUT_BYTES,
        help=(
            "Maximum bounded head and rolling-tail budget per stdout/stderr stream "
            "(default and maximum: 8 MiB)."
        ),
    )
    parser.add_argument(
        "--redact-pattern",
        action="append",
        default=[],
        help="Additional Python regex applied before diagnostics are exposed or stored.",
    )
    parser.add_argument(
        "--allow-env",
        action="append",
        default=[],
        metavar="NAME",
        help="Explicitly inherit an additional environment variable by name.",
    )
    parser.add_argument(
        "exec_args",
        nargs=argparse.REMAINDER,
        help=(
            "`-- <argv...>` to run, or `show <run-id> --errors|--tail N`, "
            "`meta <run-id>`, or `gc [--dry-run]`."
        ),
    )
