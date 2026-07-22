"""Compatibility facade for command services.

New code should import from the responsibility-specific modules. Existing
callers may continue importing these stable names from :mod:`pcl.commands`.
"""

from .action_routing import (
    TASK_ACTIONABLE_STATUSES,
    TASK_COMPLETED_DEPENDENCY_STATUSES,
    active_workflow_next_action,
    build_next_action,
    decision_options,
    escalation_options,
    generic_human_options,
    human_decision_action_fields,
    next_action,
    verification_options,
)
from .command_domain import (
    FEATURE_STATUSES,
    add_feature,
    create_goal,
    list_features,
    loop_status,
    open_defect,
    read_feature,
    set_feature_status,
)
from .finish_planning import finish_plan
from .presentation import to_pretty_json as to_pretty_json


__all__ = [
    "FEATURE_STATUSES",
    "TASK_ACTIONABLE_STATUSES",
    "TASK_COMPLETED_DEPENDENCY_STATUSES",
    "active_workflow_next_action",
    "add_feature",
    "build_next_action",
    "create_goal",
    "decision_options",
    "escalation_options",
    "finish_plan",
    "generic_human_options",
    "human_decision_action_fields",
    "list_features",
    "loop_status",
    "next_action",
    "open_defect",
    "read_feature",
    "set_feature_status",
    "to_pretty_json",
    "verification_options",
]
