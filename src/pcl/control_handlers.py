from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Callable

from . import update_check
from .audit import (
    AuditCommandError,
    audit_check as default_audit_check,
    audit_check_exit_code,
    audit_rebuild_exit_code,
    audit_repair as default_audit_repair,
    audit_repair_exit_code,
    rebuild_jsonl_from_sqlite as default_rebuild_jsonl_from_sqlite,
)
from .errors import InvalidInputError
from .init_project import init_project, plan_init_project
from .lifecycle_repair import (
    apply_structural_lifecycle_repair,
    build_lifecycle_repair_plan,
    render_lifecycle_repair_plan,
)
from .migrations import apply_migrations, migration_status
from .outbox import project_pending_events
from .paths import ProjectPaths
from .presentation import format_start_summary, to_pretty_json
from .read_handlers import handle_doctor, handle_loop_status
from .renderer import render_dashboard
from .start import start_work
from .validators import validate_project


CONTROL_COMMANDS = frozenset(
    {"init", "start", "doctor", "validate", "migrate", "audit", "repair", "render", "update", "loop"}
)


def handle_control_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    audit_check_fn: Callable = default_audit_check,
    audit_repair_fn: Callable = default_audit_repair,
    rebuild_jsonl_fn: Callable = default_rebuild_jsonl_from_sqlite,
) -> int | None:
    """Handle project initialization, maintenance, and loop-control commands."""

    if args.command not in CONTROL_COMMANDS:
        return None

    if args.command == "init":
        if args.dry_run:
            plan = plan_init_project(
                paths,
                overwrite=args.force,
                with_claude=not args.no_claude,
                repair_config=args.repair_config,
                refresh_skill=args.refresh_skill,
            )
            return _print_init_plan(plan, json_output=json_output)
        result = init_project(
            paths,
            overwrite=args.force,
            with_claude=not args.no_claude,
            repair_config=args.repair_config,
            refresh_skill=args.refresh_skill,
        )
        if json_output:
            payload = {
                "ok": True,
                "root": str(result.root),
                "created": result.created,
                "event_appended": result.event_appended,
            }
            if args.repair_config:
                payload["repaired_config_commands"] = list(result.repaired_config_commands)
            if args.refresh_skill:
                payload["skill_refreshed"] = result.skill_refreshed
                payload["skill_backup_path"] = result.skill_backup_path
            _print_json(payload)
        else:
            print(f"Initialized Project Loop Harness at {paths.root}")
            if result.repaired_config_commands:
                print(
                    "Repaired legacy empty commands: "
                    + ", ".join(result.repaired_config_commands)
                )
        return 0

    if args.command == "start":
        payload = start_work(
            paths,
            intent=args.intent,
            dry_run=args.dry_run,
            no_init=args.no_init,
            new=args.new,
            skills=args.skill,
        )
        _print_json(payload) if json_output else print(format_start_summary(payload))
        return 1 if payload["status"] == "init_blocked" else 0

    if args.command == "doctor":
        return handle_doctor(
            paths,
            strict=args.strict,
            check_updates=args.check_updates,
            json_output=json_output,
            output=sys.stdout,
        )

    if args.command == "validate":
        result = validate_project(paths, strict=args.strict)
        return _print_validation(result, json_output=json_output)

    if args.command == "migrate":
        if args.migrate_status or args.migrate_action == "status":
            status = migration_status(paths)
            payload = {"ok": True, **status.to_dict()}
            _print_json(payload) if json_output else print(to_pretty_json(payload))
            return 0
        result = apply_migrations(paths)
        if json_output:
            _print_json(result.to_dict())
        elif result.metadata_repair is not None:
            repair = result.metadata_repair
            print(
                "Repaired metadata.schema_version from "
                f"{repair['from_schema_version']} to {repair['to_schema_version']}: "
                f"{repair['reason']}. This was a metadata repair, not a schema migration."
            )
        elif result.applied:
            for migration in result.applied:
                print(f"Applied migration {migration.id}")
        else:
            print("No pending migrations")
        return 0

    if args.command == "audit" and args.audit_command == "flush":
        result = project_pending_events(paths)
        _print_json({"ok": result.ok, **result.to_dict()}) if json_output else print(
            to_pretty_json(result.to_dict())
        )
        return 0 if result.ok else 6

    if args.command == "audit" and args.audit_command == "check":
        result = audit_check_fn(paths)
        _print_json(result) if json_output else print(to_pretty_json(result))
        return audit_check_exit_code(result)

    if args.command == "audit" and args.audit_command == "repair":
        result = audit_repair_fn(paths, apply=args.apply)
        _print_json(result) if json_output else print(to_pretty_json(result))
        return audit_repair_exit_code(result)

    if args.command == "audit" and args.audit_command == "rebuild-jsonl":
        output = None if args.output is None else Path(args.output).resolve()
        try:
            result = rebuild_jsonl_fn(paths, output=output, apply=args.apply)
        except OSError as exc:
            raise AuditCommandError(
                message=f"Audit JSONL rebuild was interrupted by an I/O error: {exc}",
                code="audit_rebuild_io_error",
                exit_code=6,
            ) from exc
        _print_json(result) if json_output else print(to_pretty_json(result))
        return audit_rebuild_exit_code(result)

    if args.command == "repair" and args.repair_command == "lifecycle":
        if args.apply:
            raise InvalidInputError(
                "--apply is not supported; use --apply-structural.",
                details={"flag": "--apply", "supported_flag": "--apply-structural"},
            )
        if args.apply_structural:
            result = apply_structural_lifecycle_repair(paths)
            _print_json(result) if json_output else print(to_pretty_json(result))
            return 0
        plan = build_lifecycle_repair_plan(paths)
        _print_json(plan) if json_output else print(render_lifecycle_repair_plan(plan))
        return 0

    if args.command == "render":
        result = validate_project(paths)
        if not result.ok:
            return _print_validation(result, json_output=json_output)
        render_dashboard(paths, locale=args.locale)
        if json_output:
            _print_json(
                {
                    "data_path": str(paths.dashboard_data),
                    "ok": True,
                    "path": str(paths.dashboard_html),
                }
            )
        else:
            print(f"Rendered {paths.dashboard_html}")
        return 0

    if args.command == "update" and args.update_command == "check":
        result = update_check.check_for_update(
            timeout=args.timeout,
            use_cache=not args.no_cache,
        )
        return _print_update_check(result, json_output=json_output)

    if args.command == "update" and args.update_command == "command":
        context = update_check.detect_install_context()
        return _print_update_command(context, json_output=json_output)

    if args.command == "loop" and args.loop_command == "status":
        return handle_loop_status(paths, json_output=json_output, output=sys.stdout)

    return None


def _print_validation(result, *, json_output: bool = False) -> int:
    if json_output:
        _print_json(result.to_dict())
        return 0 if result.ok else 1
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}")
    if result.ok:
        print("OK")
        return 0
    return 1


def _print_update_check(result, *, json_output: bool = False) -> int:
    if json_output:
        _print_json(result.to_dict())
        return 0
    if result.disabled:
        print(f"Update check disabled by {update_check.NO_VERSION_CHECK_ENV}.")
    elif not result.ok:
        print(f"Update check unavailable: {result.error}")
    elif result.update_available and result.latest_version:
        print(f"Update available: pcl {result.latest_version} (current {result.current_version})")
        print(f"Run: {result.install.command}")
    else:
        print(f"pcl is up to date ({result.current_version})")
    return 0


def _print_update_command(context, *, json_output: bool = False) -> int:
    payload = {"install": context.to_dict(), "ok": True}
    _print_json(payload) if json_output else print(context.command)
    return 0


def _print_init_plan(plan, *, json_output: bool = False) -> int:
    if json_output:
        _print_json(plan.to_dict())
        return 0 if plan.ok else 1
    print(f"Init plan for {plan.root}")
    for entry in plan.changes:
        print(f"[{entry.action.upper():9}] {entry.path}  ({entry.reason})")
    for error in plan.errors:
        print(f"ERROR: {error}")
    print("No files were changed.")
    return 0 if plan.ok else 1


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
