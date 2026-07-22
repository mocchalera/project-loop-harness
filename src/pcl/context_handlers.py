from __future__ import annotations

import argparse
import json
from typing import Callable

from .code_context.summary import render_receipt_summary
from .code_index import (
    analyze_impact,
    build_code_index,
    code_index_status,
    compare_retrieval_baseline,
    evaluate_retrieval,
    propose_retrieval_fixture,
    record_retrieval_baseline,
    search_code,
)
from .context import (
    context_check_for_job,
    context_check_for_task,
    pack_context_for_job,
    pack_context_for_task,
)
from .context_usage import record_context_pack_usage
from .errors import InvalidInputError
from .paths import ProjectPaths
from .presentation import format_context_check_summary, impact_text_payload, to_pretty_json
from .receipt_show import receipt_summary_for_ref
from .timeutil import utc_now_iso


CONTEXT_COMMANDS = frozenset({"context", "receipt", "index", "code", "impact", "eval"})


def handle_context_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    now_factory: Callable[[], str] = utc_now_iso,
) -> int | None:
    """Handle context packing, receipts, code indexing, and retrieval evaluation."""

    if args.command not in CONTEXT_COMMANDS:
        return None

    if args.command == "context" and args.context_command == "pack":
        now = now_factory()
        if args.job_id:
            if args.master_trace_context:
                raise InvalidInputError(
                    "--master-trace-context is valid only with --task.",
                    details={"master_trace_context": True, "target_type": "agent_job"},
                )
            pack = pack_context_for_job(
                paths,
                job_id=args.job_id,
                now=now,
                reader_role=args.role,
                max_tokens=args.max_tokens,
                include_code_context=args.include_code_context,
                require_bound_receipt=args.require_bound_receipt,
            )
        else:
            pack = pack_context_for_task(
                paths,
                task_id=args.task_id,
                now=now,
                reader_role=args.role,
                max_tokens=args.max_tokens,
                include_code_context=args.include_code_context,
                require_bound_receipt=args.require_bound_receipt,
                include_master_trace_context=args.master_trace_context,
            )
        if args.record_usage:
            record_context_pack_usage(paths, pack)
        _print_json({"ok": True, "context_pack": pack}) if json_output else print(
            pack["markdown"], end=""
        )
        return 0

    if args.command == "context" and args.context_command == "check":
        if args.job_id:
            payload = context_check_for_job(
                paths,
                job_id=args.job_id,
                require_bound_receipt=args.require_bound_receipt,
            )
        else:
            payload = context_check_for_task(
                paths,
                task_id=args.task_id,
                require_bound_receipt=args.require_bound_receipt,
            )
        _print_json({"ok": True, "context_check": payload}) if json_output else print(
            format_context_check_summary(payload)
        )
        return 0

    if args.command == "receipt" and args.receipt_command == "show":
        summary = receipt_summary_for_ref(
            paths,
            now=now_factory(),
            ref=args.ref,
            latest=args.latest,
        )
        _print_json(summary) if json_output else print(render_receipt_summary(summary), end="")
        return 0

    if args.command == "index" and args.index_command == "build":
        result = build_code_index(paths, include_files=args.include_files)
        if json_output:
            _print_json(result)
        else:
            index = result["index"]
            print(
                f"Indexed {index['file_count']} files ({index['indexed_bytes']} bytes), "
                f"ignored {index['ignored_count']} paths "
                f"({index['sensitive_omitted_count']} sensitive)"
            )
        return 0

    if args.command == "index" and args.index_command == "status":
        result = code_index_status(paths, include_files=args.include_files)
        _print_json(result) if json_output else print(to_pretty_json(result["index"]))
        return 0

    if args.command == "code" and args.code_command == "search":
        result = search_code(paths, query=args.query, limit=args.limit)
        if json_output:
            _print_json(result)
        else:
            warning = result["search"].get("git_head_warning")
            if warning:
                print(warning["message"])
            for item in result["search"]["results"]:
                lines = item.get("lines") or []
                line = lines[0] if lines else 0
                print(f"{item['path']}:{line} {item['snippet']}")
                if item.get("snapshot_consistency") != "fresh":
                    print(
                        "  warning: "
                        f"snapshot_consistency={item['snapshot_consistency']} "
                        f"({item['snapshot_consistency_reason']})"
                    )
        return 0

    if args.command == "impact":
        result = analyze_impact(
            paths,
            diff_source=args.diff_source,
            base_ref=args.base_ref,
            staged=args.staged,
            unstaged=args.unstaged,
            include_untracked=args.include_untracked,
            all_changes=args.all_changes,
            for_task=args.for_task,
            for_job=args.for_job,
        )
        if json_output:
            _print_json(result)
        else:
            display, excluded_summary = impact_text_payload(result["impact"])
            print(to_pretty_json(display))
            if excluded_summary:
                print(excluded_summary)
        return 0

    if args.command == "eval" and args.eval_command == "retrieval":
        if args.record_baseline:
            result = record_retrieval_baseline(paths, fixture_path=args.fixture)
        elif args.compare_baseline:
            result = compare_retrieval_baseline(paths, fixture_path=args.fixture)
        else:
            result = evaluate_retrieval(paths, fixture_path=args.fixture)
        if json_output:
            _print_json(result)
        elif args.record_baseline:
            print(result["baseline"]["evidence_path"])
        elif args.compare_baseline:
            print(to_pretty_json(result["comparison"]))
        else:
            print(to_pretty_json(result["evaluation"]))
        return 0

    if (
        args.command == "eval"
        and args.eval_command == "fixture"
        and args.eval_fixture_command == "propose"
    ):
        result = propose_retrieval_fixture(
            paths,
            receipt_evidence_id=args.from_receipt,
            force=args.force,
        )
        _print_json(result) if json_output else print(result["fixture"]["path"])
        return 0

    return None


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
