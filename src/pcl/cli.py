from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

from .audit import (
    AuditCommandError,
    EXIT_AUDIT_INTERNAL,
    audit_check,
    audit_repair,
    rebuild_jsonl_from_sqlite,
)
from .control_handlers import handle_control_command
from .context_handlers import handle_context_command
from .errors import DataStoreError, InvalidInputError, PclError
from .entity_handlers import handle_entity_command
from .execution_handlers import handle_execution_command
from .paths import resolve_paths
from .parser import build_parser
from .planning_handlers import handle_planning_command
from .profile_handlers import handle_profile_command
from .read_handlers import (
    handle_guide,
)
from .timeutil import utc_now_iso
from .governance_handlers import handle_governance_command


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _print_legacy_evidence_warning(result: dict, *, json_output: bool) -> None:
    if json_output:
        return
    if any(
        warning.get("code") == "legacy_inline_evidence" for warning in result.get("warnings", [])
    ):
        print(
            "WARNING: --evidence is deprecated for terminal proof; use --evidence-id with hash-pinned Evidence.",
            file=sys.stderr,
        )


def _print_test_plan_warnings(result: dict) -> None:
    for warning in result.get("warnings", []):
        print(
            f"WARNING: {warning['message']} Suggested: {warning['suggested_command']}",
            file=sys.stderr,
        )


def _print_error(error: PclError, *, json_output: bool = False) -> None:
    if json_output:
        _print_json(error.to_dict())
        return
    print(f"ERROR: {error}", file=sys.stderr)
    allowed = error.details.get("allowed")
    if isinstance(allowed, list) and all(isinstance(value, str) for value in allowed):
        print(f"Allowed values: {', '.join(allowed)}", file=sys.stderr)
    detail_errors = error.details.get("errors")
    if isinstance(detail_errors, list):
        for detail in detail_errors:
            print(f"ERROR: {detail}", file=sys.stderr)
    detail_warnings = error.details.get("warnings")
    if isinstance(detail_warnings, list):
        for detail in detail_warnings:
            print(f"WARNING: {detail}", file=sys.stderr)


def _rubric_json_argument(args) -> str:
    if getattr(args, "rubric_file", None):
        rubric_path = Path(args.rubric_file)
        try:
            return rubric_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvalidInputError(
                f"Could not read rubric file: {args.rubric_file}",
                details={"path": args.rubric_file},
            ) from exc
    rubric_json = getattr(args, "rubric_json", None)
    return "{}" if rubric_json is None else rubric_json


def _extract_global_options(argv: list[str] | None) -> tuple[list[str] | None, str | None, bool]:
    """Allow global options before or after subcommands for agent-friendliness.

    argparse normally requires global options before the subcommand. Coding agents
    often place --root/--json at the end, so we normalize them here.
    """
    if argv is None:
        argv = sys.argv[1:]
    normalized: list[str] = []
    root_override: str | None = None
    json_output = False
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--root" and i + 1 < len(argv):
            root_override = argv[i + 1]
            i += 2
            continue
        if token.startswith("--root="):
            root_override = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--json":
            json_output = True
            i += 1
            continue
        normalized.append(token)
        i += 1
    return normalized, root_override, json_output


def main(argv: list[str] | None = None) -> int:
    argv, root_override, json_override = _extract_global_options(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    root = getattr(args, "target", None) or root_override or args.root
    paths = resolve_paths(root)
    json_output = json_override or args.json

    try:
        if args.command == "guide":
            return handle_guide(args.topic, json_output=json_output, output=sys.stdout)

        profile_status = handle_profile_command(args, paths, json_output=json_output)
        if profile_status is not None:
            return profile_status

        control_status = handle_control_command(
            args,
            paths,
            json_output=json_output,
            audit_check_fn=audit_check,
            audit_repair_fn=audit_repair,
            rebuild_jsonl_fn=rebuild_jsonl_from_sqlite,
        )
        if control_status is not None:
            return control_status

        entity_status = handle_entity_command(
            args,
            paths,
            json_output=json_output,
            output=sys.stdout,
            error=sys.stderr,
        )
        if entity_status is not None:
            return entity_status

        execution_status = handle_execution_command(
            args,
            paths,
            json_output=json_output,
            output=sys.stdout,
            error=sys.stderr,
        )
        if execution_status is not None:
            return execution_status

        governance_status = handle_governance_command(
            args,
            paths,
            json_output=json_output,
            rubric_json=_rubric_json_argument(args)
            if args.command == "verification" and args.verification_command == "record"
            else None,
            output=sys.stdout,
            error=sys.stderr,
        )
        if governance_status is not None:
            return governance_status

        context_status = handle_context_command(
            args,
            paths,
            json_output=json_output,
            now_factory=utc_now_iso,
        )
        if context_status is not None:
            return context_status

        planning_status = handle_planning_command(args, paths, json_output=json_output)
        if planning_status is not None:
            return planning_status

        parser.error("Unhandled command")
        return 2
    except PclError as exc:
        _print_error(exc, json_output=json_output)
        return exc.exit_code
    except OSError as exc:
        if args.command == "audit":
            error = AuditCommandError(
                message=f"Audit command failed: {exc}",
                code="audit_internal_error",
                exit_code=EXIT_AUDIT_INTERNAL,
            )
            _print_error(error, json_output=json_output)
            return error.exit_code
        raise
    except sqlite3.Error as exc:
        if args.command == "audit":
            error = AuditCommandError(
                message=f"SQLite error while running audit: {exc}",
                code="audit_internal_error",
                exit_code=EXIT_AUDIT_INTERNAL,
            )
            _print_error(error, json_output=json_output)
            return error.exit_code
        error = DataStoreError(f"SQLite error while running {args.command}: {exc}")
        _print_error(error, json_output=json_output)
        return error.exit_code
    except Exception as exc:
        if args.command == "audit":
            error = AuditCommandError(
                message=f"Audit command failed unexpectedly: {exc}",
                code="audit_internal_error",
                exit_code=EXIT_AUDIT_INTERNAL,
            )
            _print_error(error, json_output=json_output)
            return error.exit_code
        raise


if __name__ == "__main__":
    raise SystemExit(main())
