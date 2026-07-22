from __future__ import annotations


def add_planning_parsers(sub) -> None:
    p_guide = sub.add_parser(
        "guide", help="Show purpose-oriented command routes for agents and operators"
    )
    p_guide.add_argument(
        "topic",
        nargs="?",
        default=None,
        help="Optional topic: start, direct, finish, dashboard, or recover",
    )

    p_next = sub.add_parser("next", help="Suggest the next harness action")
    p_next.add_argument(
        "--strict",
        action="store_true",
        help="Route strict validation failures before normal next actions",
    )
    p_next.add_argument(
        "--explain",
        action="store_true",
        help="Print a human-readable explanation of the next action",
    )
    p_next.add_argument(
        "--target",
        dest="next_target",
        default=None,
        help="Bind routing to an existing Task or Goal ID",
    )

    p_finish = sub.add_parser("finish", help="Plan terminal loop close-out steps")
    p_finish.add_argument(
        "--execute",
        action="store_true",
        help="Run validate/render only when no finish steps remain",
    )
    p_finish.add_argument(
        "--emit-packet",
        action="store_true",
        help="Run configured guarded checks and emit a completion-packet/v1 artifact",
    )
    p_finish.add_argument(
        "--dry-run",
        action="store_true",
        help="With --emit-packet, preview the target, repository snapshot, and guarded check plan",
    )
    p_finish.add_argument("--run", default=None, help="Target a workflow run explicitly")
    p_finish.add_argument("--goal", default=None, help="Target a goal explicitly")
    p_finish.add_argument(
        "--task", default=None, help="Target a task for completion packet emission"
    )
    p_finish.add_argument(
        "--base", default=None, help="Git base revision for the completion packet diff"
    )
    p_finish.add_argument("--timeout", type=int, default=120, help="Per-check timeout in seconds")
    p_finish.add_argument(
        "--max-output-bytes",
        type=int,
        default=1_048_576,
        help="Maximum retained stdout and stderr bytes per check stream",
    )

    p_resume = sub.add_parser("resume", help="Build a read-only handoff packet for current work")
    p_resume.add_argument(
        "--target",
        dest="resume_target",
        default=None,
        help="Task or goal ID; required when multiple active targets exist",
    )
    p_resume.add_argument(
        "--format",
        choices=["json", "markdown"],
        default=None,
        help="Output format (default: markdown; --json selects JSON)",
    )
    p_resume.add_argument(
        "--output", default=None, help="Also write the rendered packet to this path"
    )

    p_export = sub.add_parser("export", help="Export state")
    export_sub = p_export.add_subparsers(dest="export_command", required=True)
    export_sub.add_parser("csv")

    p_report = sub.add_parser("report", help="Generate evidence reports")
    report_sub = p_report.add_subparsers(dest="report_command", required=True)
    p_report_goal = report_sub.add_parser("goal")
    p_report_goal.add_argument("goal_id")
    p_report_run = report_sub.add_parser("run")
    p_report_run.add_argument("workflow_run_id")
    p_report_feature = report_sub.add_parser("feature")
    p_report_feature.add_argument("feature_id")
    p_report_defect = report_sub.add_parser("defect")
    p_report_defect.add_argument("defect_id")
    p_report_validation = report_sub.add_parser("validation")
    p_report_validation.add_argument("--strict", action="store_true")
    p_report_kpi = report_sub.add_parser("kpi", help="Read local dogfood KPI measurements")
    p_report_kpi.add_argument(
        "--since", default=None, help="Include records on or after YYYY-MM-DD"
    )
    p_report_skill_usage = report_sub.add_parser(
        "skill-usage",
        help="Read local Codex, Claude, and Cockpit Skill usage without retaining raw logs",
    )
    p_report_skill_usage.add_argument(
        "--since",
        default=None,
        help="Include local log signals on or after YYYY-MM-DD (default: 30 days ago)",
    )
    p_report_skill_usage.add_argument(
        "--until",
        default=None,
        help="Include local log signals on or before YYYY-MM-DD (default: today)",
    )
    p_report_skill_usage.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source to scan: codex, claude, or cockpit. Repeat to select multiple.",
    )
    p_report_skill_usage.add_argument("--codex-root", default=None)
    p_report_skill_usage.add_argument("--claude-root", default=None)
    p_report_skill_usage.add_argument("--cockpit-root", default=None)
    p_report_skill_usage.add_argument(
        "--output",
        default=None,
        help="Also atomically write the privacy-safe JSON or Markdown report to this path",
    )
