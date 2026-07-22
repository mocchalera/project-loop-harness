from __future__ import annotations

import argparse
from io import StringIO
import json
from pathlib import Path

import pytest

from pcl.cli import build_parser
from pcl.entity_handlers import handle_entity_command
from pcl.errors import ProjectNotInitializedError
from pcl.init_project import init_project
from pcl.paths import resolve_paths


def _args(*values: str) -> argparse.Namespace:
    return build_parser().parse_args(list(values))


def _handle_json(paths, *values: str) -> dict:
    output = StringIO()
    assert (
        handle_entity_command(
            _args(*values),
            paths,
            json_output=True,
            output=output,
            error=StringIO(),
        )
        == 0
    )
    assert output.getvalue().endswith("\n")
    return json.loads(output.getvalue())


def test_entity_handler_dispatches_each_family_with_deterministic_ids(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)

    goal = _handle_json(paths, "goal", "create", "--title", "Refactor")
    feature = _handle_json(
        paths,
        "feature",
        "add",
        "--name",
        "Entity handlers",
        "--surface",
        "cli",
    )
    story = _handle_json(
        paths,
        "story",
        "draft",
        "--feature",
        feature["id"],
        "--actor",
        "maintainer",
        "--goal",
        "preserve behavior",
        "--expected-behavior",
        "entity commands remain compatible",
    )
    test_case = _handle_json(
        paths,
        "test",
        "plan",
        "--feature",
        feature["id"],
        "--story",
        story["id"],
        "--type",
        "acceptance",
        "--scenario",
        "invoke the extracted handler",
        "--expected",
        "the existing result is preserved",
    )
    task = _handle_json(
        paths,
        "task",
        "create",
        "--title",
        "Exercise handler",
        "--goal",
        goal["id"],
    )
    defect = _handle_json(
        paths,
        "defect",
        "open",
        "--feature",
        feature["id"],
        "--severity",
        "low",
        "--expected",
        "stable output",
        "--actual",
        "characterization fixture",
    )

    assert goal == {"id": "G-0001", "ok": True}
    assert feature == {"id": "F-0001", "ok": True}
    assert story["id"] == "US-0001"
    assert test_case["id"] == "TC-0001"
    assert task["id"] == "T-0001"
    assert defect == {"id": "D-0001", "ok": True}


def test_entity_handler_preserves_text_list_output(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    _handle_json(
        paths,
        "feature",
        "add",
        "--name",
        "Stable feature",
        "--surface",
        "cli",
    )
    output = StringIO()

    assert (
        handle_entity_command(
            _args("feature", "list"),
            paths,
            json_output=False,
            output=output,
            error=StringIO(),
        )
        == 0
    )

    assert output.getvalue() == "F-0001 discovered surface=cli name=Stable feature\n"


def test_entity_handler_returns_none_without_output_for_other_families(tmp_path: Path) -> None:
    output = StringIO()
    error = StringIO()

    assert (
        handle_entity_command(
            argparse.Namespace(command="guide"),
            resolve_paths(tmp_path),
            json_output=True,
            output=output,
            error=error,
        )
        is None
    )
    assert output.getvalue() == ""
    assert error.getvalue() == ""


def test_entity_handler_preserves_uninitialized_zero_output(tmp_path: Path) -> None:
    output = StringIO()

    with pytest.raises(ProjectNotInitializedError):
        handle_entity_command(
            _args("goal", "create", "--title", "Refactor"),
            resolve_paths(tmp_path),
            json_output=True,
            output=output,
            error=StringIO(),
        )

    assert output.getvalue() == ""
    assert list(tmp_path.iterdir()) == []
