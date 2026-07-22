from __future__ import annotations

import argparse
import json
from pathlib import Path

from pcl.cli import build_parser
from pcl.context_handlers import handle_context_command
from pcl.control_handlers import handle_control_command
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.planning_handlers import handle_planning_command
from pcl.profile_handlers import handle_profile_command


def _args(*values: str) -> argparse.Namespace:
    return build_parser().parse_args(list(values))


def test_profile_handler_lists_profiles_with_existing_json_shape(
    tmp_path: Path,
    capsys,
) -> None:
    status = handle_profile_command(
        _args("profile", "list"),
        resolve_paths(tmp_path),
        json_output=True,
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["contract_version"] == "profile-registry/v1"
    assert payload["profiles"]


def test_control_handler_init_dry_run_remains_non_mutating(
    tmp_path: Path,
    capsys,
) -> None:
    status = handle_control_command(
        _args("init", "--target", str(tmp_path), "--dry-run"),
        resolve_paths(tmp_path),
        json_output=True,
    )

    assert status == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert not (tmp_path / ".project-loop").exists()


def test_context_and_planning_handlers_dispatch_directly(
    tmp_path: Path,
    capsys,
) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)

    assert (
        handle_context_command(
            _args("index", "status"),
            paths,
            json_output=True,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert (
        handle_planning_command(
            _args("next"),
            paths,
            json_output=True,
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["type"] == "idle"


def test_control_stage_handlers_return_none_for_other_families(tmp_path: Path) -> None:
    args = argparse.Namespace(command="goal")
    paths = resolve_paths(tmp_path)

    assert handle_profile_command(args, paths, json_output=True) is None
    assert handle_control_command(args, paths, json_output=True) is None
    assert handle_context_command(args, paths, json_output=True) is None
    assert handle_planning_command(args, paths, json_output=True) is None
