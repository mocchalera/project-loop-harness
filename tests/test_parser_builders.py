from __future__ import annotations

import argparse

import pytest

from pcl.cli import build_parser as cli_build_parser
from pcl.parser import build_parser


EXPECTED_COMMANDS = [
    "init",
    "start",
    "doctor",
    "validate",
    "migrate",
    "audit",
    "repair",
    "render",
    "update",
    "goal",
    "feature",
    "story",
    "test",
    "task",
    "defect",
    "loop",
    "workflow",
    "jobs",
    "prompt",
    "agent",
    "ingest-agent-run",
    "evidence",
    "profile",
    "contract",
    "evidence-set",
    "completion",
    "brief",
    "gap",
    "route",
    "policy",
    "context",
    "receipt",
    "index",
    "code",
    "impact",
    "eval",
    "verification",
    "decision",
    "escalation",
    "checkpoint",
    "guide",
    "next",
    "finish",
    "resume",
    "export",
    "report",
]


def test_cli_reexports_parser_facade_and_preserves_registration_order() -> None:
    assert cli_build_parser is build_parser
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert list(subparsers.choices) == EXPECTED_COMMANDS


def test_every_top_level_command_has_working_help(capsys) -> None:
    parser = build_parser()

    for command in EXPECTED_COMMANDS:
        with pytest.raises(SystemExit) as exit_info:
            parser.parse_args([command, "--help"])
        assert exit_info.value.code == 0
        assert f"usage: pcl {command}" in capsys.readouterr().out


def test_family_builders_preserve_representative_defaults_and_destinations() -> None:
    parser = build_parser()

    assert parser.parse_args(["start", "literal intent"]).intent == "literal intent"
    assert parser.parse_args(["feature", "list"]).feature_command == "list"
    assert parser.parse_args(["loop", "status"]).loop_command == "status"
    assert parser.parse_args(["profile", "list"]).profile_command == "list"
    assert parser.parse_args(["impact", "--diff"]).diff_source == "__git__"
    assert parser.parse_args(["verification", "list"]).verification_command == "list"
    assert parser.parse_args(["next"]).next_target is None
