from __future__ import annotations

import argparse
from io import StringIO
import json
from pathlib import Path

from pcl.cli import build_parser
from pcl.commands import add_feature, create_goal
from pcl.execution_handlers import handle_execution_command
from pcl.governance_handlers import handle_governance_command
from pcl.init_project import init_project
from pcl.paths import resolve_paths


def _args(*values: str) -> argparse.Namespace:
    return build_parser().parse_args(list(values))


def test_execution_handler_runs_workflow_and_preserves_json_shape(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    goal_id = create_goal(paths, title="Coverage")
    add_feature(paths, name="CLI", surface="runtime")
    output = StringIO()

    assert (
        handle_execution_command(
            _args("loop", "run", "feature_coverage", "--goal", goal_id),
            paths,
            json_output=True,
            output=output,
            error=StringIO(),
        )
        == 0
    )

    payload = json.loads(output.getvalue())
    assert payload["ok"] is True
    assert payload["workflow_run"]["id"] == "WR-0001"
    assert [job["id"] for job in payload["jobs"]] == ["J-0001", "J-0002", "J-0003"]


def test_execution_handler_preserves_agent_register_text(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    output = StringIO()

    assert (
        handle_execution_command(
            _args(
                "agent",
                "register",
                "--name",
                "worker",
                "--role",
                "implementer",
                "--adapter",
                "manual",
            ),
            paths,
            json_output=False,
            output=output,
            error=StringIO(),
        )
        == 0
    )

    assert output.getvalue() == "Registered agent A-0001\n"


def test_governance_handler_records_copied_evidence(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    artifact = tmp_path / "result.txt"
    artifact.write_text("verified\n", encoding="utf-8")
    output = StringIO()

    assert (
        handle_governance_command(
            _args(
                "evidence",
                "add",
                "--file",
                str(artifact),
                "--summary",
                "handler result",
                "--copy",
            ),
            paths,
            json_output=True,
            output=output,
            error=StringIO(),
        )
        == 0
    )

    payload = json.loads(output.getvalue())
    assert payload["evidence"]["id"] == "E-0001"
    assert payload["evidence"]["members"][0]["storage_mode"] == "copied"


def test_governance_handler_preserves_decision_text(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    output = StringIO()

    assert (
        handle_governance_command(
            _args(
                "decision",
                "open",
                "--question",
                "Proceed?",
                "--recommendation",
                "Review evidence",
            ),
            paths,
            json_output=False,
            output=output,
            error=StringIO(),
        )
        == 0
    )

    assert output.getvalue() == "DEC-0001\n"


def test_stage3_handlers_return_none_without_output_for_other_families(tmp_path: Path) -> None:
    args = argparse.Namespace(command="context")
    output = StringIO()
    error = StringIO()
    paths = resolve_paths(tmp_path)

    assert (
        handle_execution_command(
            args,
            paths,
            json_output=True,
            output=output,
            error=error,
        )
        is None
    )
    assert (
        handle_governance_command(
            args,
            paths,
            json_output=True,
            output=output,
            error=error,
        )
        is None
    )
    assert output.getvalue() == ""
    assert error.getvalue() == ""
