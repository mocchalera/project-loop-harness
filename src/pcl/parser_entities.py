from __future__ import annotations

from .commands import FEATURE_STATUSES
from .parser_common import choices_help
from .stories import STORY_STATUSES, TEST_CASE_STATUSES, TEST_CASE_TYPES
from .tasks import TASK_RISKS, TASK_STATUSES


def add_entity_parsers(sub) -> None:
    p_goal = sub.add_parser("goal", help="Manage goals")
    goal_sub = p_goal.add_subparsers(dest="goal_command", required=True)
    p_goal_create = goal_sub.add_parser("create")
    p_goal_create.add_argument("--title", required=True)
    p_goal_create.add_argument("--completion-json", default="{}")
    p_goal_create.add_argument("--budget-json", default="{}")
    p_goal_close = goal_sub.add_parser("close")
    p_goal_close.add_argument("goal_id")
    p_goal_close.add_argument("--summary", required=True)
    goal_evidence = p_goal_close.add_mutually_exclusive_group()
    goal_evidence.add_argument("--evidence", default="")
    goal_evidence.add_argument("--evidence-id", default=None)
    p_goal_close.add_argument("--verification", default=None)
    p_goal_cancel = goal_sub.add_parser("cancel")
    p_goal_cancel.add_argument("goal_id")
    p_goal_cancel.add_argument("--summary", required=True)

    p_feature = sub.add_parser("feature", help="Manage features")
    feature_sub = p_feature.add_subparsers(dest="feature_command", required=True)
    p_feature_add = feature_sub.add_parser("add")
    p_feature_add.add_argument("--name", required=True)
    p_feature_add.add_argument("--surface", required=True)
    p_feature_add.add_argument("--description", default="")
    p_feature_add.add_argument("--evidence", default="")
    p_feature_add.add_argument(
        "--task", default=None, help="Atomically link the new Feature to an existing Task"
    )
    p_feature_list = feature_sub.add_parser("list")
    p_feature_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by feature status: {choices_help(FEATURE_STATUSES)}",
    )
    p_feature_read = feature_sub.add_parser("read")
    p_feature_read.add_argument("feature_id")
    p_feature_status = feature_sub.add_parser("status")
    p_feature_status.add_argument("feature_id")
    p_feature_status.add_argument(
        "--status",
        default="",
        help=f"Target feature status: {choices_help(FEATURE_STATUSES)}",
    )
    p_feature_status.add_argument("--summary", default="")
    feature_evidence = p_feature_status.add_mutually_exclusive_group()
    feature_evidence.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as command output, artifact path, screenshot path, commit, or report path.",
    )
    feature_evidence.add_argument("--evidence-id", default=None)

    p_story = sub.add_parser("story", help="Manage user stories")
    story_sub = p_story.add_subparsers(dest="story_command", required=True)
    p_story_draft = story_sub.add_parser("draft")
    p_story_draft.add_argument("--feature", required=True)
    p_story_draft.add_argument("--actor", required=True)
    p_story_draft.add_argument("--goal", required=True)
    p_story_draft.add_argument("--benefit", default="")
    p_story_draft.add_argument("--expected-behavior", required=True)
    p_story_review = story_sub.add_parser("review")
    p_story_review.add_argument("story_id")
    p_story_review.add_argument("--summary", required=True)
    p_story_approve = story_sub.add_parser("approve")
    p_story_approve.add_argument("story_id")
    p_story_approve.add_argument("--summary", required=True)
    p_story_waive = story_sub.add_parser("waive")
    p_story_waive.add_argument("story_id")
    p_story_waive.add_argument("--reason", required=True)
    p_story_list = story_sub.add_parser("list")
    p_story_list.add_argument("--feature", default=None)
    p_story_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by story status: {choices_help(STORY_STATUSES)}",
    )
    p_story_read = story_sub.add_parser("read")
    p_story_read.add_argument("story_id")

    p_test = sub.add_parser("test", help="Manage test cases")
    test_sub = p_test.add_subparsers(dest="test_command", required=True)
    p_test_plan = test_sub.add_parser("plan")
    p_test_plan.add_argument("--feature", required=True)
    p_test_plan.add_argument("--story", default=None)
    p_test_plan.add_argument(
        "--type",
        required=True,
        help=f"Test case type: {choices_help(TEST_CASE_TYPES)}",
    )
    p_test_plan.add_argument("--scenario", required=True)
    p_test_plan.add_argument("--expected", required=True)
    p_test_link = test_sub.add_parser(
        "link", help="Repair Story and Evidence relationships without replaying Test status"
    )
    p_test_link.add_argument("test_case_id")
    p_test_link.add_argument("--story", default=None)
    p_test_link.add_argument("--evidence-id", default=None)
    p_test_link.add_argument("--summary", required=True)
    p_test_pass = test_sub.add_parser("pass")
    p_test_pass.add_argument("test_case_id")
    p_test_pass.add_argument("--summary", required=True)
    test_pass_evidence = p_test_pass.add_mutually_exclusive_group()
    test_pass_evidence.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as command output, artifact path, screenshot path, commit, or report path.",
    )
    test_pass_evidence.add_argument("--evidence-id", default=None)
    p_test_pass.add_argument("--run", default=None)
    p_test_pass.add_argument(
        "--completion-policy",
        default=None,
        dest="completion_policy_file",
        help="completion-policy/v1 JSON required when --evidence-id is an evidence_set receipt.",
    )
    p_test_reverify = test_sub.add_parser(
        "reverify",
        help="Replace proof for a passing Test with an evaluated Evidence Set",
    )
    p_test_reverify.add_argument("test_case_id")
    p_test_reverify.add_argument("--summary", required=True)
    p_test_reverify.add_argument("--evidence-id", required=True)
    p_test_reverify.add_argument(
        "--completion-policy",
        required=True,
        dest="completion_policy_file",
        help="completion-policy/v1 JSON evaluated against the exact target-bound Evidence Set.",
    )
    p_test_fail = test_sub.add_parser("fail")
    p_test_fail.add_argument("test_case_id")
    p_test_fail.add_argument("--summary", required=True)
    test_fail_evidence = p_test_fail.add_mutually_exclusive_group()
    test_fail_evidence.add_argument(
        "--evidence",
        default="",
        help="Reviewer-checkable proof, such as failing command output, artifact path, screenshot path, or report path.",
    )
    test_fail_evidence.add_argument("--evidence-id", default=None)
    p_test_fail.add_argument("--run", default=None)
    p_test_block = test_sub.add_parser("block")
    p_test_block.add_argument("test_case_id")
    p_test_block.add_argument("--summary", required=True)
    p_test_block.add_argument("--run", default=None)
    p_test_missing = test_sub.add_parser("missing")
    p_test_missing.add_argument("test_case_id")
    p_test_missing.add_argument("--summary", required=True)
    p_test_waive = test_sub.add_parser("waive")
    p_test_waive.add_argument("test_case_id")
    p_test_waive.add_argument("--reason", required=True)
    p_test_list = test_sub.add_parser("list")
    p_test_list.add_argument("--feature", default=None)
    p_test_list.add_argument("--story", default=None)
    p_test_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by test case status: {choices_help(TEST_CASE_STATUSES)}",
    )
    p_test_read = test_sub.add_parser("read")
    p_test_read.add_argument("test_case_id")

    p_task = sub.add_parser("task", help="Manage tasks")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)
    p_task_create = task_sub.add_parser("create")
    p_task_create.add_argument("--title", required=True)
    p_task_create.add_argument("--description", default="")
    p_task_create.add_argument("--priority", type=int, default=100)
    p_task_create.add_argument("--owner", default="")
    p_task_create.add_argument(
        "--risk", default=None, help=f"Task risk: {choices_help(TASK_RISKS)}"
    )
    p_task_create.add_argument("--effort", default="")
    p_task_create.add_argument("--goal", default=None)
    p_task_create.add_argument("--feature", default=None)
    p_task_create.add_argument("--defect", default=None)
    p_task_list = task_sub.add_parser("list")
    p_task_list.add_argument(
        "--status",
        default=None,
        help=f"Filter by task status: {choices_help(TASK_STATUSES)}",
    )
    p_task_list.add_argument("--goal", default=None)
    p_task_list.add_argument("--owner", default=None)
    p_task_read = task_sub.add_parser("read")
    p_task_read.add_argument("task_id")
    p_task_status = task_sub.add_parser("status")
    p_task_status.add_argument("task_id")
    p_task_status.add_argument(
        "new_status", help=f"Target task status: {choices_help(TASK_STATUSES)}"
    )
    p_task_status.add_argument("--reason", required=True)
    p_task_depend = task_sub.add_parser("depend")
    p_task_depend.add_argument("task_id")
    p_task_depend.add_argument("--on", required=True, dest="depends_on_task_id")
    p_task_undepend = task_sub.add_parser("undepend")
    p_task_undepend.add_argument("task_id")
    p_task_undepend.add_argument("--on", required=True, dest="depends_on_task_id")

    p_defect = sub.add_parser("defect", help="Manage defects")
    defect_sub = p_defect.add_subparsers(dest="defect_command", required=True)
    p_defect_open = defect_sub.add_parser("open")
    p_defect_open.add_argument("--feature", required=True)
    p_defect_open.add_argument(
        "--severity", required=True, choices=["critical", "high", "medium", "low"]
    )
    p_defect_open.add_argument("--expected", required=True)
    p_defect_open.add_argument("--actual", required=True)
    p_defect_open.add_argument("--test", default=None)
    p_defect_open.add_argument("--reproduction", default="")
    p_defect_open.add_argument("--evidence", default="")
    p_defect_triage = defect_sub.add_parser("triage")
    p_defect_triage.add_argument("defect_id")
    p_defect_triage.add_argument("--summary", required=True)
    p_defect_start = defect_sub.add_parser("start")
    p_defect_start.add_argument("defect_id")
    p_defect_start.add_argument("--summary", required=True)
    p_defect_fix = defect_sub.add_parser("fix")
    p_defect_fix.add_argument("defect_id")
    p_defect_fix.add_argument("--summary", required=True)
    p_defect_fix.add_argument("--evidence", default="")
    p_defect_verify = defect_sub.add_parser("verify")
    p_defect_verify.add_argument("defect_id")
    p_defect_verify.add_argument("--summary", required=True)
    p_defect_verify.add_argument("--verification", required=True)
    p_defect_close = defect_sub.add_parser("close")
    p_defect_close.add_argument("defect_id")
    p_defect_close.add_argument("--summary", required=True)
    p_defect_close.add_argument("--evidence", default="")
    p_defect_waive = defect_sub.add_parser("waive")
    p_defect_waive.add_argument("defect_id")
    p_defect_waive.add_argument("--reason", default="")
