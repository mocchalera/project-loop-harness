from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

import pytest

from pcl.command_guide import command_guide, render_command_guide
from pcl.commands import loop_status, to_pretty_json
from pcl.errors import InvalidInputError, ProjectNotInitializedError
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.read_handlers import handle_guide, handle_loop_status


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_guide_handler_json_matches_existing_contract_bytes() -> None:
    output = StringIO()

    assert handle_guide("finish", json_output=True, output=output) == 0

    expected = json.dumps(command_guide("finish"), ensure_ascii=False, sort_keys=True) + "\n"
    assert output.getvalue() == expected


def test_guide_handler_text_matches_existing_renderer_bytes() -> None:
    output = StringIO()

    assert handle_guide(None, json_output=False, output=output) == 0

    assert output.getvalue() == render_command_guide(command_guide())


def test_guide_handler_preserves_typed_error_and_writes_nothing() -> None:
    output = StringIO()

    with pytest.raises(InvalidInputError) as caught:
        handle_guide("unknown", json_output=True, output=output)

    assert caught.value.details == {
        "topic": "unknown",
        "supported_topics": ["start", "direct", "finish", "dashboard", "recover"],
    }
    assert output.getvalue() == ""


@pytest.mark.parametrize("json_output", [False, True])
def test_loop_status_handler_preserves_output_and_all_project_bytes(
    tmp_path: Path, json_output: bool
) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    status = loop_status(paths)
    before = _file_snapshot(paths.loop_dir)
    output = StringIO()

    assert handle_loop_status(paths, json_output=json_output, output=output) == 0

    if json_output:
        expected = json.dumps(status, ensure_ascii=False, sort_keys=True) + "\n"
    else:
        expected = to_pretty_json(status) + "\n"
    assert output.getvalue() == expected
    assert _file_snapshot(paths.loop_dir) == before


def test_loop_status_handler_preserves_not_initialized_error_and_writes_nothing(
    tmp_path: Path,
) -> None:
    output = StringIO()

    with pytest.raises(ProjectNotInitializedError):
        handle_loop_status(resolve_paths(tmp_path), json_output=True, output=output)

    assert output.getvalue() == ""
    assert list(tmp_path.iterdir()) == []
