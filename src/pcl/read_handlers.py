from __future__ import annotations

import json
from typing import TextIO

from . import update_check
from .command_guide import command_guide, render_command_guide
from .commands import loop_status, to_pretty_json
from .paths import ProjectPaths
from .reports import report_defect, report_feature, report_goal, report_run, report_validation
from .validators import validate_project


def handle_doctor(
    paths: ProjectPaths,
    *,
    strict: bool,
    check_updates: bool,
    json_output: bool,
    output: TextIO,
) -> int:
    result = validate_project(paths, strict=strict, include_config_advice=True)
    update_result = update_check.check_for_update() if check_updates else None
    if update_result is not None:
        if update_result.update_available and update_result.latest_version:
            result.add_warning(
                f"pcl {update_result.latest_version} is available; "
                f"run `{update_result.install.command}`.",
                code="update_available",
                entity={"type": "package", "id": "project-loop-harness"},
                repair_class="human_review",
                requires_human=True,
            )
        elif not update_result.ok and not update_result.disabled:
            result.add_warning(
                f"Could not check for pcl updates: {update_result.error}",
                code="update_check_failed",
                entity={"type": "package", "id": "project-loop-harness"},
                repair_class="unsupported",
            )

    if json_output:
        payload = result.to_dict()
        if update_result is not None:
            payload["update"] = update_result.to_dict()
        output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return 0 if result.ok else 1

    for warning in result.warnings:
        output.write(f"WARNING: {warning}\n")
    for error in result.errors:
        output.write(f"ERROR: {error}\n")
    if result.ok:
        output.write("OK\n")
    if update_result is not None and result.ok:
        if update_result.disabled:
            output.write(f"Update check disabled by {update_check.NO_VERSION_CHECK_ENV}.\n")
        elif update_result.ok and not update_result.update_available:
            output.write(
                f"Update check: pcl is up to date ({update_result.current_version})\n"
            )
    return 0 if result.ok else 1


def handle_guide(topic: str | None, *, json_output: bool, output: TextIO) -> int:
    result = command_guide(topic)
    if json_output:
        output.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        output.write(render_command_guide(result))
    return 0


def handle_loop_status(paths: ProjectPaths, *, json_output: bool, output: TextIO) -> int:
    status = loop_status(paths)
    if json_output:
        output.write(json.dumps(status, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        output.write(to_pretty_json(status) + "\n")
    return 0


def handle_report_artifact(
    paths: ProjectPaths,
    report_command: str,
    *,
    identifier: str | None,
    strict: bool,
    json_output: bool,
    output: TextIO,
) -> int:
    if report_command == "goal":
        result = report_goal(paths, str(identifier))
    elif report_command == "run":
        result = report_run(paths, str(identifier))
    elif report_command == "feature":
        result = report_feature(paths, str(identifier))
    elif report_command == "defect":
        result = report_defect(paths, str(identifier))
    elif report_command == "validation":
        result = report_validation(paths, strict=strict)
    else:
        raise ValueError(f"Unsupported report artifact command: {report_command}")

    if json_output:
        output.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        output.write(f"{result['path']}\n")
    return 0
