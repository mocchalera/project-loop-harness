from __future__ import annotations

import argparse

from .agent_output_renderer import AGENT_OUTPUT_HOSTS


def add_agent_output_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "agent-output",
        help="Inspect the canonical agent output-budget policy without executing commands",
        description=(
            "Classify already-tokenized argv and render deterministic host guidance. "
            "This surface never executes or rewrites the observed command."
        ),
    )
    output_sub = parser.add_subparsers(dest="agent_output_command", required=True)
    output_sub.add_parser(
        "policy",
        help="Print the versioned canonical agent-output policy",
    )
    classify = output_sub.add_parser(
        "classify",
        help="Classify one JSON array of already-tokenized argv items",
    )
    classify.add_argument(
        "--argv-json",
        required=True,
        help="JSON array of argv tokens; shell strings are never parsed",
    )
    render = output_sub.add_parser(
        "render",
        help="Render one deterministic host projection from the shared Skill",
    )
    render.add_argument("--host", required=True, choices=AGENT_OUTPUT_HOSTS)
