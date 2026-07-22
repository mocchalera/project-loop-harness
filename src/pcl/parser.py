from __future__ import annotations

import argparse

from . import __version__
from .parser_context import add_context_parsers
from .parser_control import add_control_parsers
from .parser_entities import add_entity_parsers
from .parser_execution import add_execution_parsers
from .parser_governance import add_governance_parsers
from .parser_planning import add_planning_parsers
from .parser_work_inputs import add_work_input_parsers


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser while preserving command registration order."""

    parser = argparse.ArgumentParser(prog="pcl", description="Project Loop Harness CLI")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument("--version", action="version", version=f"pcl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    add_control_parsers(sub)
    add_entity_parsers(sub)
    add_execution_parsers(sub)
    add_work_input_parsers(sub)
    add_context_parsers(sub)
    add_governance_parsers(sub)
    add_planning_parsers(sub)
    return parser
