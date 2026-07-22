from __future__ import annotations

import argparse
import json
import sys

from .commands import build_next_action, finish_plan, next_action
from .errors import InvalidInputError
from .exporters import export_csv
from .finish_execution import emit_finish_packet, plan_finish_packet
from .kpi_report import report_kpi
from .paths import ProjectPaths
from .presentation import format_finish_summary, format_next_explanation, to_pretty_json
from .read_handlers import handle_report_artifact
from .renderer import render_dashboard
from .skill_usage_report import (
    default_skill_usage_roots,
    render_skill_usage_markdown,
    report_skill_usage,
    serialized_skill_usage_report,
    write_skill_usage_report,
)
from .validators import validate_project


PLANNING_COMMANDS = frozenset({"next", "finish", "export", "report"})


def handle_planning_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
) -> int | None:
    """Handle next-action, finish, export, and report commands."""

    if args.command not in PLANNING_COMMANDS:
        return None

    if args.command == "next":
        if args.strict:
            validation = validate_project(paths, strict=True)
            if not validation.ok:
                action = build_next_action(
                    action_type="resolve_validation_errors",
                    command="pcl report validation --strict",
                    reason="Strict validation failed; review diagnostics before continuing the loop.",
                    target={
                        "strict": True,
                        "ok": validation.ok,
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                        "findings": [finding.to_dict() for finding in validation.findings],
                        "finding_count": len(validation.findings),
                        "finding_counts": validation.finding_counts(),
                        "finding_codes": [finding.code for finding in validation.findings],
                        "validation_report": ".project-loop/reports/validation-strict.md",
                    },
                    priority=1,
                    blocking=True,
                    requires_human=True,
                    safe_to_run=True,
                    expected_after="Strict validation passes and normal next-action routing can resume.",
                )
            else:
                action = next_action(paths, target=args.next_target)
        else:
            action = next_action(paths, target=args.next_target)
        if json_output:
            _print_json(action)
        elif args.explain:
            print(format_next_explanation(action))
        else:
            print(to_pretty_json(action))
        return 0

    if args.command == "finish":
        packet_only_flags = any(
            [
                args.dry_run,
                args.task,
                args.base,
                args.timeout != 120,
                args.max_output_bytes != 1_048_576,
            ]
        )
        if args.execute and args.emit_packet:
            raise InvalidInputError(
                "--execute and --emit-packet are separate modes and cannot be combined."
            )
        if packet_only_flags and not args.emit_packet:
            raise InvalidInputError(
                "--dry-run, --task, --base, --timeout, and --max-output-bytes require --emit-packet."
            )
        if args.emit_packet:
            if args.dry_run:
                packet_payload = plan_finish_packet(
                    paths,
                    run_id=args.run,
                    goal_id=args.goal,
                    task_id=args.task,
                    base_revision=args.base,
                )
                packet_payload["exit_code"] = 0
            else:
                packet_payload = emit_finish_packet(
                    paths,
                    run_id=args.run,
                    goal_id=args.goal,
                    task_id=args.task,
                    base_revision=args.base,
                    timeout_seconds=args.timeout,
                    max_output_bytes=args.max_output_bytes,
                )
            _print_json({"ok": True, "finish": packet_payload}) if json_output else print(
                to_pretty_json(packet_payload)
            )
            return int(packet_payload["exit_code"])
        payload = finish_plan(paths, run_id=args.run, goal_id=args.goal)
        exit_code = 0
        if args.execute:
            payload = dict(payload)
            if payload["remaining_steps"]:
                payload["executed"] = []
                payload["changed"] = False
            else:
                executed = _run_finish_tail(paths)
                payload["executed"] = executed
                payload["changed"] = bool(executed)
                if any(not item["ok"] for item in executed):
                    exit_code = 1
        _print_json({"ok": True, "finish": payload}) if json_output else print(
            format_finish_summary(payload)
        )
        return exit_code

    if args.command == "export" and args.export_command == "csv":
        paths_written = export_csv(paths)
        if json_output:
            _print_json({"ok": True, "paths": [str(path) for path in paths_written]})
        else:
            for path in paths_written:
                print(path)
        return 0

    if args.command == "report" and args.report_command in {
        "goal",
        "run",
        "feature",
        "defect",
        "validation",
    }:
        identifier_attributes = {
            "goal": "goal_id",
            "run": "workflow_run_id",
            "feature": "feature_id",
            "defect": "defect_id",
        }
        identifier = getattr(args, identifier_attributes.get(args.report_command, ""), None)
        return handle_report_artifact(
            paths,
            args.report_command,
            identifier=identifier,
            strict=getattr(args, "strict", False),
            json_output=json_output,
            output=sys.stdout,
        )

    if args.command == "report" and args.report_command == "kpi":
        result = report_kpi(paths, since=args.since)
        _print_json(result) if json_output else print(to_pretty_json(result["sections"]))
        return 0

    if args.command == "report" and args.report_command == "skill-usage":
        result = report_skill_usage(
            since=args.since,
            until=args.until,
            sources=args.source or None,
            codex_root=args.codex_root,
            claude_root=args.claude_root,
            cockpit_root=args.cockpit_root,
        )
        rendered = (
            serialized_skill_usage_report(result)
            if json_output
            else render_skill_usage_markdown(result)
        )
        if args.output:
            source_roots = default_skill_usage_roots(
                codex_root=args.codex_root,
                claude_root=args.claude_root,
                cockpit_root=args.cockpit_root,
            )
            write_skill_usage_report(
                args.output,
                rendered,
                forbidden_roots=source_roots.values(),
                forbidden_paths=(
                    paths.db_path,
                    paths.events_path,
                    paths.dashboard_html,
                    paths.dashboard_data,
                ),
            )
        print(rendered, end="")
        return 0

    return None


def _run_finish_tail(paths: ProjectPaths) -> list[dict]:
    executed: list[dict] = []
    strict = validate_project(paths, strict=True)
    executed.append({"command": "pcl validate --strict", "ok": strict.ok})
    if not strict.ok:
        return executed
    render_validation = validate_project(paths)
    if not render_validation.ok:
        executed.append({"command": "pcl render", "ok": False})
        return executed
    render_dashboard(paths)
    executed.append({"command": "pcl render", "ok": True})
    return executed


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
