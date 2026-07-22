from __future__ import annotations

from pathlib import Path

from pcl import commands
from pcl.action_routing import build_next_action, next_action
from pcl.command_domain import create_goal, loop_status
from pcl.finish_planning import finish_plan
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.presentation import to_pretty_json


def test_commands_facade_reexports_stable_service_names() -> None:
    for name in commands.__all__:
        assert hasattr(commands, name)

    assert commands.create_goal is create_goal
    assert commands.loop_status is loop_status
    assert commands.build_next_action is build_next_action
    assert commands.next_action is next_action
    assert commands.finish_plan is finish_plan
    assert commands.to_pretty_json is to_pretty_json


def test_commands_facade_preserves_domain_routing_and_finish_behavior(tmp_path: Path) -> None:
    paths = resolve_paths(tmp_path)
    init_project(paths)

    goal_id = commands.create_goal(paths, title="Compatibility")
    feature_id = commands.add_feature(paths, name="Facade", surface="commands")

    status = commands.loop_status(paths)
    action = commands.next_action(paths, target=goal_id)
    finish = commands.finish_plan(paths, goal_id=goal_id)

    assert goal_id == "G-0001"
    assert feature_id == "F-0001"
    assert status["open_goals"][0]["id"] == goal_id
    assert action["target_binding"]["target_id"] == goal_id
    assert finish["target"] == {"run": None, "goal": goal_id}
    assert finish["remaining_steps"][0]["type"] == "continue_goal"
