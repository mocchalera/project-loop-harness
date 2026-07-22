from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from .commands import (
    add_feature,
    create_goal,
    list_features,
    open_defect,
    read_feature,
    set_feature_status,
)
from .lifecycle import (
    cancel_goal,
    close_defect,
    close_goal,
    fix_defect,
    start_defect,
    triage_defect,
    verify_defect,
    waive_defect,
)
from .paths import ProjectPaths
from .presentation import to_pretty_json
from .relationship_repair import repair_test_links
from .stories import (
    approve_story,
    block_test_case,
    draft_story,
    fail_test_case,
    list_stories,
    list_test_cases,
    missing_test_case,
    pass_test_case,
    plan_test_case,
    read_story,
    read_test_case,
    reverify_test_case,
    review_story,
    waive_story,
    waive_test_case,
)
from .tasks import (
    add_dependency,
    create_task,
    list_tasks,
    read_task,
    remove_dependency,
    set_task_status,
)


ENTITY_COMMANDS = frozenset({"goal", "feature", "story", "test", "task", "defect"})


def handle_entity_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    *,
    json_output: bool,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int | None:
    """Handle entity lifecycle commands, or return ``None`` when unhandled."""

    if args.command not in ENTITY_COMMANDS:
        return None

    if args.command == "goal" and args.goal_command == "create":
        goal_id = create_goal(
            paths,
            title=args.title,
            completion_json=args.completion_json,
            budget_json=args.budget_json,
        )
        _write_json({"id": goal_id, "ok": True}, output) if json_output else print(
            goal_id, file=output
        )
        return 0

    if args.command == "goal" and args.goal_command == "close":
        result = close_goal(
            paths,
            goal_id=args.goal_id,
            summary=args.summary,
            evidence=args.evidence,
            evidence_id=args.evidence_id,
            verification_id=args.verification,
        )
        _print_legacy_evidence_warning(result, json_output=json_output, error=error)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Goal {result['goal_id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Closed goal {result['goal_id']}", file=output)
        return 0

    if args.command == "goal" and args.goal_command == "cancel":
        result = cancel_goal(paths, goal_id=args.goal_id, summary=args.summary)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Goal {result['goal_id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Cancelled goal {result['goal_id']}", file=output)
        return 0

    if args.command == "feature" and args.feature_command == "add":
        feature_id = add_feature(
            paths,
            name=args.name,
            surface=args.surface,
            description=args.description,
            evidence=args.evidence,
            task_id=args.task,
        )
        _write_json({"id": feature_id, "ok": True}, output) if json_output else print(
            feature_id, file=output
        )
        return 0

    if args.command == "feature" and args.feature_command == "list":
        features = list_features(paths, status=args.status)
        if json_output:
            _write_json({"features": features, "ok": True}, output)
        elif features:
            for feature in features:
                print(
                    f"{feature['id']} {feature['status']} surface={feature['surface']} "
                    f"name={feature['name']}",
                    file=output,
                )
        else:
            print("No features", file=output)
        return 0

    if args.command == "feature" and args.feature_command == "read":
        feature = read_feature(paths, args.feature_id)
        if json_output:
            _write_json({"feature": feature, "ok": True}, output)
        else:
            print(to_pretty_json(feature), file=output)
        return 0

    if args.command == "feature" and args.feature_command == "status":
        result = set_feature_status(
            paths,
            args.feature_id,
            status=args.status,
            summary=args.summary,
            evidence=args.evidence,
            evidence_id=args.evidence_id,
        )
        _print_legacy_evidence_warning(result, json_output=json_output, error=error)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Feature {result['feature_id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Updated feature {result['feature_id']} to {result['status']}", file=output)
        return 0

    if args.command == "story" and args.story_command == "draft":
        result = draft_story(
            paths,
            feature_id=args.feature,
            actor=args.actor,
            goal=args.goal,
            benefit=args.benefit,
            expected_behavior=args.expected_behavior,
        )
        _write_json(result, output) if json_output else print(result["id"], file=output)
        return 0

    if args.command == "story" and args.story_command == "review":
        result = review_story(paths, story_id=args.story_id, summary=args.summary)
        _write_json(result, output) if json_output else print(
            f"Reviewed story {result['id']}", file=output
        )
        return 0

    if args.command == "story" and args.story_command == "approve":
        result = approve_story(paths, story_id=args.story_id, summary=args.summary)
        _write_json(result, output) if json_output else print(
            f"Approved story {result['id']}", file=output
        )
        return 0

    if args.command == "story" and args.story_command == "waive":
        result = waive_story(paths, story_id=args.story_id, reason=args.reason)
        _write_json(result, output) if json_output else print(
            f"Waived story {result['id']}", file=output
        )
        return 0

    if args.command == "story" and args.story_command == "list":
        stories = list_stories(paths, feature_id=args.feature, status=args.status)
        if json_output:
            _write_json({"ok": True, "stories": stories}, output)
        elif stories:
            for story in stories:
                print(
                    f"{story['id']} {story['status']} feature={story['feature_id']} "
                    f"goal={story['goal']}",
                    file=output,
                )
        else:
            print("No stories", file=output)
        return 0

    if args.command == "story" and args.story_command == "read":
        story = read_story(paths, args.story_id)
        if json_output:
            _write_json({"ok": True, "story": story}, output)
        else:
            print(to_pretty_json(story), file=output)
        return 0

    if args.command == "test" and args.test_command == "plan":
        result = plan_test_case(
            paths,
            feature_id=args.feature,
            story_id=args.story,
            test_type=args.type,
            scenario=args.scenario,
            expected=args.expected,
        )
        if json_output:
            _write_json(result, output)
        else:
            print(result["id"], file=output)
            _print_test_plan_warnings(result, error=error)
        return 0

    if args.command == "test" and args.test_command == "link":
        result = repair_test_links(
            paths,
            test_case_id=args.test_case_id,
            story_id=args.story,
            evidence_id=args.evidence_id,
            summary=args.summary,
        )
        _write_json(result, output) if json_output else print(to_pretty_json(result), file=output)
        return 0

    if args.command == "test" and args.test_command == "pass":
        result = pass_test_case(
            paths,
            test_case_id=args.test_case_id,
            summary=args.summary,
            evidence=args.evidence,
            evidence_id=args.evidence_id,
            workflow_run_id=args.run,
            completion_policy_file=args.completion_policy_file,
        )
        _print_legacy_evidence_warning(result, json_output=json_output, error=error)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Test case {result['id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Passed test case {result['id']}", file=output)
        return 0

    if args.command == "test" and args.test_command == "reverify":
        result = reverify_test_case(
            paths,
            test_case_id=args.test_case_id,
            summary=args.summary,
            evidence_id=args.evidence_id,
            completion_policy_file=args.completion_policy_file,
        )
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Test case {result['id']} already has this reverified proof; no change recorded.",
                file=output,
            )
        else:
            print(f"Reverified test case {result['id']}", file=output)
        return 0

    if args.command == "test" and args.test_command == "fail":
        result = fail_test_case(
            paths,
            test_case_id=args.test_case_id,
            summary=args.summary,
            evidence=args.evidence,
            evidence_id=args.evidence_id,
            workflow_run_id=args.run,
        )
        _print_legacy_evidence_warning(result, json_output=json_output, error=error)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Test case {result['id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Failed test case {result['id']}", file=output)
        return 0

    if args.command == "test" and args.test_command == "block":
        result = block_test_case(
            paths,
            test_case_id=args.test_case_id,
            summary=args.summary,
            workflow_run_id=args.run,
        )
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Test case {result['id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Blocked test case {result['id']}", file=output)
        return 0

    if args.command == "test" and args.test_command == "missing":
        result = missing_test_case(paths, test_case_id=args.test_case_id, summary=args.summary)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Test case {result['id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Marked test case {result['id']} missing", file=output)
        return 0

    if args.command == "test" and args.test_command == "waive":
        result = waive_test_case(paths, test_case_id=args.test_case_id, reason=args.reason)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(
                f"Test case {result['id']} already {result['status']}; no change recorded.",
                file=output,
            )
        else:
            print(f"Waived test case {result['id']}", file=output)
        return 0

    if args.command == "test" and args.test_command == "list":
        test_cases = list_test_cases(
            paths,
            feature_id=args.feature,
            story_id=args.story,
            status=args.status,
        )
        if json_output:
            _write_json({"ok": True, "test_cases": test_cases}, output)
        elif test_cases:
            for test_case in test_cases:
                print(
                    f"{test_case['id']} {test_case['status']} "
                    f"feature={test_case['feature_id']} type={test_case['type']}",
                    file=output,
                )
        else:
            print("No test cases", file=output)
        return 0

    if args.command == "test" and args.test_command == "read":
        test_case = read_test_case(paths, args.test_case_id)
        if json_output:
            _write_json({"ok": True, "test_case": test_case}, output)
        else:
            print(to_pretty_json(test_case), file=output)
        return 0

    if args.command == "task" and args.task_command == "create":
        result = create_task(
            paths,
            title=args.title,
            description=args.description,
            priority=args.priority,
            owner=args.owner,
            risk=args.risk,
            effort=args.effort,
            goal_id=args.goal,
            feature_id=args.feature,
            defect_id=args.defect,
        )
        _write_json(result, output) if json_output else print(result["id"], file=output)
        return 0

    if args.command == "task" and args.task_command == "list":
        tasks = list_tasks(paths, status=args.status, goal_id=args.goal, owner=args.owner)
        if json_output:
            _write_json({"ok": True, "tasks": tasks}, output)
        elif tasks:
            for task in tasks:
                print(
                    f"{task['id']} {task['status']} priority={task['priority']} "
                    f"title={task['title']}",
                    file=output,
                )
        else:
            print("No tasks", file=output)
        return 0

    if args.command == "task" and args.task_command == "read":
        task = read_task(paths, args.task_id)
        if json_output:
            _write_json({"ok": True, "task": task}, output)
        else:
            print(to_pretty_json(task), file=output)
        return 0

    if args.command == "task" and args.task_command == "status":
        result = set_task_status(paths, args.task_id, status=args.new_status, reason=args.reason)
        if json_output:
            _write_json(result, output)
        elif result.get("changed") is False:
            print(f"Task {result['id']} already {result['status']}; no change recorded.", file=output)
        else:
            print(
                f"Updated task {result['id']} from {result['from_status']} "
                f"to {result['to_status']}",
                file=output,
            )
        return 0

    if args.command == "task" and args.task_command == "depend":
        result = add_dependency(paths, args.task_id, depends_on_task_id=args.depends_on_task_id)
        if json_output:
            _write_json(result, output)
        else:
            print(
                f"Added task dependency {result['task_id']} -> {result['depends_on_task_id']}",
                file=output,
            )
        return 0

    if args.command == "task" and args.task_command == "undepend":
        result = remove_dependency(
            paths,
            args.task_id,
            depends_on_task_id=args.depends_on_task_id,
        )
        if json_output:
            _write_json(result, output)
        else:
            print(
                f"Removed task dependency {result['task_id']} -> "
                f"{result['depends_on_task_id']}",
                file=output,
            )
        return 0

    if args.command == "defect" and args.defect_command == "open":
        defect_id = open_defect(
            paths,
            feature_id=args.feature,
            severity=args.severity,
            expected=args.expected,
            actual=args.actual,
            test_case_id=args.test,
            reproduction=args.reproduction,
            evidence=args.evidence,
        )
        _write_json({"id": defect_id, "ok": True}, output) if json_output else print(
            defect_id, file=output
        )
        return 0

    if args.command == "defect" and args.defect_command == "triage":
        result = triage_defect(paths, defect_id=args.defect_id, summary=args.summary)
        _write_json(result, output) if json_output else print(
            f"Triaged defect {result['defect_id']}", file=output
        )
        return 0

    if args.command == "defect" and args.defect_command == "start":
        result = start_defect(paths, defect_id=args.defect_id, summary=args.summary)
        _write_json(result, output) if json_output else print(
            f"Started defect {result['defect_id']}", file=output
        )
        return 0

    if args.command == "defect" and args.defect_command == "fix":
        result = fix_defect(
            paths,
            defect_id=args.defect_id,
            summary=args.summary,
            evidence=args.evidence,
        )
        _write_json(result, output) if json_output else print(
            f"Fixed defect {result['defect_id']}", file=output
        )
        return 0

    if args.command == "defect" and args.defect_command == "verify":
        result = verify_defect(
            paths,
            defect_id=args.defect_id,
            summary=args.summary,
            verification_id=args.verification,
        )
        _write_json(result, output) if json_output else print(
            f"Verified defect {result['defect_id']}", file=output
        )
        return 0

    if args.command == "defect" and args.defect_command == "close":
        result = close_defect(
            paths,
            defect_id=args.defect_id,
            summary=args.summary,
            evidence=args.evidence,
        )
        _write_json(result, output) if json_output else print(
            f"Closed defect {result['defect_id']}", file=output
        )
        return 0

    if args.command == "defect" and args.defect_command == "waive":
        result = waive_defect(paths, defect_id=args.defect_id, reason=args.reason)
        _write_json(result, output) if json_output else print(
            f"Waived defect {result['defect_id']}", file=output
        )
        return 0

    raise AssertionError(f"Unhandled entity command: {args.command}")


def _write_json(payload: object, output: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=output)


def _print_legacy_evidence_warning(
    result: dict,
    *,
    json_output: bool,
    error: TextIO,
) -> None:
    if json_output:
        return
    if any(
        warning.get("code") == "legacy_inline_evidence" for warning in result.get("warnings", [])
    ):
        print(
            "WARNING: --evidence is deprecated for terminal proof; use --evidence-id with "
            "hash-pinned Evidence.",
            file=error,
        )


def _print_test_plan_warnings(result: dict, *, error: TextIO) -> None:
    for warning in result.get("warnings", []):
        print(
            f"WARNING: {warning['message']} Suggested: {warning['suggested_command']}",
            file=error,
        )
