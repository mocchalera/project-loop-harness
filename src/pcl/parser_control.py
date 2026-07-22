from __future__ import annotations

import argparse

from . import update_check


def add_control_parsers(sub) -> None:
    p_init = sub.add_parser("init", help="Initialize Project Loop Harness in a target project")
    p_init.add_argument("--target", default=None, help="Target project root. Overrides --root.")
    init_write_mode = p_init.add_mutually_exclusive_group()
    init_write_mode.add_argument(
        "--force", action="store_true", help="Overwrite template files where safe"
    )
    init_write_mode.add_argument(
        "--repair-config",
        action="store_true",
        help="Normalize legacy empty command placeholders to null without overwriting pcl.yaml",
    )
    init_write_mode.add_argument(
        "--refresh-skill",
        action="store_true",
        help=(
            "Refresh only the bundled project-control-loop Skill, preserving the replaced "
            "bytes in a hash-addressed backup"
        ),
    )
    p_init.add_argument("--no-claude", action="store_true", help="Do not create/update CLAUDE.md")
    p_init.add_argument(
        "--dry-run", action="store_true", help="Inspect the init plan without writing files"
    )

    p_start = sub.add_parser("start", help="Start one intent as minimal active project work")
    p_start.add_argument(
        "intent", help="Natural-language intent; preserved literally and never executed"
    )
    p_start.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview initialization and state changes without mutation",
    )
    p_start.add_argument(
        "--no-init",
        action="store_true",
        help="Stop instead of initializing an uninitialized project",
    )
    p_start.add_argument(
        "--new",
        action="store_true",
        help="Start separate work even when active work already exists",
    )
    p_start.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Readable Skill file to hash before mutation; repeatable",
    )

    p_doctor = sub.add_parser("doctor", help="Check project-loop installation health")
    p_doctor.add_argument("--strict", action="store_true")
    p_doctor.add_argument(
        "--check-updates",
        action="store_true",
        help="Also check PyPI for a newer project-loop-harness release.",
    )

    p_validate = sub.add_parser("validate", help="Validate project-loop state")
    p_validate.add_argument("--strict", action="store_true")

    p_migrate = sub.add_parser("migrate", help="Apply or inspect database migrations")
    p_migrate.add_argument(
        "migrate_action",
        nargs="?",
        choices=["apply", "status"],
        default="apply",
        help="Use `status` to inspect migrations without applying them.",
    )
    p_migrate.add_argument(
        "--status",
        action="store_true",
        dest="migrate_status",
        help="Inspect migrations without applying them.",
    )

    p_audit = sub.add_parser("audit", help="Manage the SQLite-backed audit projection")
    audit_sub = p_audit.add_subparsers(dest="audit_command", required=True)
    audit_sub.add_parser("flush", help="Project eligible committed events to events.jsonl")
    audit_sub.add_parser("check", help="Read-only integrity check for audit and Evidence state")
    p_audit_repair = audit_sub.add_parser(
        "repair",
        help="Preview or apply supported audit repairs; preview is the default",
    )
    repair_mode = p_audit_repair.add_mutually_exclusive_group()
    repair_mode.add_argument("--dry-run", action="store_true", help="Preview without mutation")
    repair_mode.add_argument("--apply", action="store_true", help="Apply the displayed repair plan")
    p_audit_rebuild = audit_sub.add_parser(
        "rebuild-jsonl",
        help="Generate a verified events.jsonl projection from authoritative SQLite events",
    )
    p_audit_rebuild.add_argument(
        "--from-sqlite",
        action="store_true",
        required=True,
        help="Use authoritative SQLite events as the rebuild source",
    )

    p_audit_rebuild.add_argument("--output", default=None, help="Preview output path")
    p_audit_rebuild.add_argument(
        "--apply",
        action="store_true",
        help="Backup and atomically replace events.jsonl, then record an audit event",
    )

    p_repair = sub.add_parser("repair", help="Plan repairs for existing project state")
    repair_sub = p_repair.add_subparsers(dest="repair_command", required=True)
    p_repair_lifecycle = repair_sub.add_parser(
        "lifecycle",
        help="Build a deterministic read-only lifecycle repair plan",
    )
    p_repair_lifecycle.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly select the default read-only planning mode",
    )
    p_repair_lifecycle.add_argument(
        "--apply-structural",
        action="store_true",
        help="Atomically apply only recognized safe structural actions from the current plan",
    )
    p_repair_lifecycle.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)

    p_render = sub.add_parser("render", help="Render dashboard from state")
    p_render.add_argument("--locale", default=None, help="Dashboard HTML locale: en, ja")

    p_update = sub.add_parser("update", help="Check for newer pcl releases")
    update_sub = p_update.add_subparsers(dest="update_command", required=True)
    p_update_check = update_sub.add_parser("check", help="Check PyPI for a newer release")
    p_update_check.add_argument(
        "--no-cache", action="store_true", help="Bypass the local 24h cache"
    )
    p_update_check.add_argument(
        "--timeout",
        type=float,
        default=update_check.DEFAULT_TIMEOUT_SECONDS,
        help="Network timeout in seconds.",
    )
    update_sub.add_parser("command", help="Print the recommended manual upgrade command")
