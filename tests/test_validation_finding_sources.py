from __future__ import annotations

import ast
from pathlib import Path
import shlex

from pcl.cli import build_parser
from pcl.validators import _artifact_inspection_commands, _pcl_json_command, _pcl_root_command


VALIDATORS = Path("src/pcl/validators.py")
EMISSIONS = {"add_error", "add_warning"}
STRUCTURED_HELPERS = {
    "_add_lifecycle_finding",
    "_add_rubric_validation_problem",
    "error",
    "warning",
}


def _function_for(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current: ast.AST | None = node
    while current is not None and not isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
        current = parents.get(current)
    return (
        current.name if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)) else "<module>"
    )


def test_every_validation_emission_has_an_explicit_source_code() -> None:
    tree = ast.parse(VALIDATORS.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    missing: list[str] = []
    unjustified_unpacking: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in EMISSIONS:
            continue
        function = _function_for(node, parents)
        if any(keyword.arg == "code" for keyword in node.keywords):
            continue
        if any(keyword.arg is None for keyword in node.keywords):
            if function not in STRUCTURED_HELPERS:
                unjustified_unpacking.append(f"{node.lineno}:{function}")
            continue
        missing.append(f"{node.lineno}:{function}:{node.func.attr}")
    assert missing == []
    assert unjustified_unpacking == []


def test_representative_validator_families_use_distinct_codes_and_entities() -> None:
    tree = ast.parse(VALIDATORS.read_text(encoding="utf-8"))
    calls: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        code_keyword = next((item for item in node.keywords if item.arg == "code"), None)
        if (
            code_keyword
            and isinstance(code_keyword.value, ast.Constant)
            and isinstance(code_keyword.value.value, str)
        ):
            calls[code_keyword.value.value] = node

    expected = {
        "installation_events_missing",
        "schema_required_table_missing",
        "audit_projection_event_missing",
        "workflow_proposal_file_missing",
        "verification_rubric_evidence_missing",
        "artifact_missing",
        "relationship_foreign_key_violation",
        "relationship_terminal_goal_active_workflow",
        "relationship_job_agent_missing",
        "agent_lease_expired",
        "agent_concurrency_exceeded",
        "task_dependency_cycle",
        "task_done_dependency_incomplete",
    }
    assert expected <= calls.keys()
    assert len(expected) == len(set(expected))
    helper_derived_entities = {"audit_projection_event_missing"}
    for code in expected - helper_derived_entities:
        assert any(keyword.arg == "entity" for keyword in calls[code].keywords), code


def test_every_representative_suggested_command_parses_without_execution() -> None:
    commands = {
        "pcl init --target /tmp/pcl-guidance-project",
        _pcl_root_command("/tmp/pcl-guidance-project", "migrate"),
        _pcl_json_command("migrate", "status"),
        _pcl_json_command("audit", "check"),
        _pcl_json_command("repair", "lifecycle", "--dry-run"),
        _pcl_json_command("agent", "list"),
        _pcl_json_command("verification", "read", "V-0001"),
        _pcl_json_command("workflow", "proposals", "list"),
        _pcl_json_command("workflow", "proposals", "read", "WP-0001"),
        _pcl_json_command("story", "read", "US-0001"),
        _pcl_json_command("test", "read", "TC-0001"),
        _pcl_json_command("task", "read", "T-0001"),
        _pcl_json_command("jobs", "read", "J-0001"),
        _pcl_json_command("jobs", "reap"),
        _pcl_json_command("loop", "status"),
        "pcl report validation --strict",
        *_artifact_inspection_commands({"type": "evidence", "id": "E-0001"}),
        *_artifact_inspection_commands({"type": "agent_job", "id": "J-0001"}),
    }
    parser = build_parser()
    for command in sorted(commands):
        assert not any(marker in command for marker in ("<", ">", "...", "PATH", " ID")), command
        argv = shlex.split(command)
        assert argv[0] == "pcl"
        parser.parse_args(argv[1:])
