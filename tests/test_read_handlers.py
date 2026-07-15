from __future__ import annotations

from io import StringIO
import json
from pathlib import Path

import pytest

from pcl import update_check
from pcl.command_guide import command_guide, render_command_guide
from pcl.commands import loop_status, to_pretty_json
from pcl.errors import InvalidInputError, ProjectNotInitializedError
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.read_handlers import handle_doctor, handle_guide, handle_loop_status
from pcl.validators import validate_project


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
def test_doctor_handler_preserves_output_and_all_project_bytes(
    monkeypatch, tmp_path: Path, json_output: bool
) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    result = validate_project(paths, include_config_advice=True)
    before = _file_snapshot(paths.loop_dir)
    output = StringIO()

    def unexpected_update_check(**_kwargs):
        raise AssertionError("doctor must keep update checking opt-in")

    monkeypatch.setattr(update_check, "check_for_update", unexpected_update_check)

    assert (
        handle_doctor(
            paths,
            strict=False,
            check_updates=False,
            json_output=json_output,
            output=output,
        )
        == 0
    )

    if json_output:
        expected = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    else:
        expected = "".join(f"WARNING: {warning}\n" for warning in result.warnings) + "OK\n"
    assert output.getvalue() == expected
    assert _file_snapshot(paths.loop_dir) == before


def test_doctor_handler_preserves_update_advice_json_and_project_bytes(
    monkeypatch, tmp_path: Path
) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)
    install = update_check.InstallContext(
        method="pipx",
        command="pipx upgrade project-loop-harness",
        reason="test install context",
    )
    update_result = update_check.UpdateCheckResult(
        ok=True,
        package="project-loop-harness",
        current_version="0.5.1",
        latest_version="0.5.2",
        update_available=True,
        source_url="https://pypi.org/pypi/project-loop-harness/json",
        checked_at="2026-07-16T00:00:00Z",
        install=install,
    )
    monkeypatch.setattr(update_check, "check_for_update", lambda **_kwargs: update_result)
    expected_result = validate_project(paths, include_config_advice=True)
    expected_result.add_warning(
        "pcl 0.5.2 is available; run `pipx upgrade project-loop-harness`.",
        code="update_available",
        entity={"type": "package", "id": "project-loop-harness"},
        repair_class="human_review",
        requires_human=True,
    )
    expected_payload = expected_result.to_dict()
    expected_payload["update"] = update_result.to_dict()
    before = _file_snapshot(paths.loop_dir)
    output = StringIO()

    assert (
        handle_doctor(
            paths,
            strict=False,
            check_updates=True,
            json_output=True,
            output=output,
        )
        == 0
    )

    expected = json.dumps(expected_payload, ensure_ascii=False, sort_keys=True) + "\n"
    assert output.getvalue() == expected
    assert _file_snapshot(paths.loop_dir) == before


@pytest.mark.parametrize("json_output", [False, True])
def test_doctor_handler_preserves_uninitialized_failure_without_writes(
    tmp_path: Path, json_output: bool
) -> None:
    paths = resolve_paths(tmp_path)
    result = validate_project(paths, strict=True, include_config_advice=True)
    output = StringIO()

    assert (
        handle_doctor(
            paths,
            strict=True,
            check_updates=False,
            json_output=json_output,
            output=output,
        )
        == 1
    )

    if json_output:
        expected = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
    else:
        expected = "".join(f"ERROR: {error}\n" for error in result.errors)
    assert output.getvalue() == expected
    assert list(tmp_path.iterdir()) == []


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
