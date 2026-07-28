from __future__ import annotations

import json
from pathlib import Path
import re
import shlex

from pcl.cli import _extract_global_options, build_parser, main
from pcl.command_guide import command_guide


TOPICS = ["start", "direct", "finish", "dashboard", "recover"]
AUTHORITY_CLASSES = [
    "read_only",
    "pcl_local_state",
    "repository_write",
    "external_write",
    "terminal_transition",
]
STEP_KEYS = {
    "order",
    "command",
    "mutates_state",
    "run_policy",
    "requires",
    "purpose",
    "expected_after",
    "authority_class",
    "human_decision_required",
    "human_decision_basis",
    "evidence_requirement",
    "failure_recovery",
}


def _json_output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_guide_json_is_complete_deterministic_and_read_only_before_init(
    tmp_path: Path, capsys
) -> None:
    before = sorted(path.name for path in tmp_path.iterdir())

    assert main(["--root", str(tmp_path), "guide", "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["--root", str(tmp_path), "guide", "--json"]) == 0
    second = capsys.readouterr().out

    assert first == second
    payload = json.loads(first)
    assert payload["ok"] is True
    assert payload["contract_version"] == "command-guide/v1"
    assert payload["requested_topic"] is None
    assert [item["id"] for item in payload["authority_classes"]] == AUTHORITY_CLASSES
    assert [item["topic"] for item in payload["topics"]] == TOPICS
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    assert not (tmp_path / ".project-loop").exists()
    for topic in payload["topics"]:
        assert topic["steps"]
        assert [step["order"] for step in topic["steps"]] == list(
            range(1, len(topic["steps"]) + 1)
        )
        assert all(set(step) == STEP_KEYS for step in topic["steps"])


def test_guide_topic_returns_canonical_direct_route(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "guide", "direct", "--json"]) == 0
    payload = _json_output(capsys)

    assert payload["requested_topic"] == "direct"
    assert [item["topic"] for item in payload["topics"]] == ["direct"]
    steps = payload["topics"][0]["steps"]
    commands = [step["command"] for step in steps]
    assert commands[0] == 'pcl start "<literal intent>" --json'
    assert any("story approve <story_id>" in command for command in commands)
    assert any("--evidence-id <evidence_id>" in command for command in commands)
    assert "pcl finish --emit-packet --goal <goal_id> --json" in commands
    assert any("pcl goal close <goal_id>" in command for command in commands)
    approval = next(step for step in steps if "story approve" in step["command"])
    assert approval["run_policy"] == "human_required"
    assert approval["mutates_state"] is True
    assert approval["authority_class"] == "terminal_transition"
    assert approval["human_decision_required"] is True
    assert approval["human_decision_basis"]
    assert approval["failure_recovery"] == "pcl story read <story_id> --json"


def test_guide_separates_authority_from_domain_state_mutation() -> None:
    payload = command_guide()
    steps = [
        step
        for topic in payload["topics"]
        for step in topic["steps"]
    ]

    assert all(step["authority_class"] in AUTHORITY_CLASSES for step in steps)
    assert not any(step["authority_class"] == "external_write" for step in steps)
    assert all(
        step["mutates_state"] is False
        for step in steps
        if step["authority_class"] == "read_only"
    )
    assert all(
        step["authority_class"] == "repository_write"
        for step in steps
        if step["command"] in {"pcl init --json", "pcl render --json"}
    )
    assert all(
        step["authority_class"] != "read_only"
        for step in steps
        if step["mutates_state"]
    )


def test_terminal_guide_steps_have_fail_closed_operator_contracts() -> None:
    terminal_steps = [
        step
        for topic in command_guide()["topics"]
        for step in topic["steps"]
        if step["authority_class"] == "terminal_transition"
    ]

    assert terminal_steps
    assert any(step["human_decision_required"] for step in terminal_steps)
    for step in terminal_steps:
        assert step["requires"]
        assert isinstance(step["human_decision_required"], bool)
        assert step["human_decision_basis"]
        assert step["failure_recovery"]
        if "--evidence-id" in step["command"]:
            assert step["evidence_requirement"]

        recovery = re.sub(r"<[^>]+>", "VALUE", step["failure_recovery"])
        argv = shlex.split(recovery)
        assert argv[0] == "pcl"
        normalized, _root, _json = _extract_global_options(argv[1:])
        build_parser().parse_args(normalized)
        assert not any(
            token in step["failure_recovery"]
            for token in (" close ", " pass ", "--status done", " status ")
        )


def test_guide_unknown_topic_uses_typed_invalid_input(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "guide", "unknown", "--json"]) == 2
    payload = _json_output(capsys)

    assert payload == {
        "error": {
            "code": "invalid_input",
            "details": {"supported_topics": TOPICS, "topic": "unknown"},
            "message": "Unknown command guide topic.",
        },
        "ok": False,
    }


def test_every_guide_command_template_satisfies_current_parser_contract() -> None:
    for topic in command_guide()["topics"]:
        for step in topic["steps"]:
            command = re.sub(r"<[^>]+>", "VALUE", step["command"])
            argv = shlex.split(command)
            assert argv[0] == "pcl"
            normalized, _root, _json = _extract_global_options(argv[1:])
            build_parser().parse_args(normalized)


def test_guide_text_and_skill_route_uncertainty_to_structured_guide(
    tmp_path: Path, capsys
) -> None:
    assert main(["--root", str(tmp_path), "guide", "finish"]) == 0
    first = capsys.readouterr().out
    assert main(["--root", str(tmp_path), "guide", "finish"]) == 0
    second = capsys.readouterr().out

    assert first == second
    assert "Command guide: finish" in first
    assert "pcl finish --emit-packet --goal <goal_id> --json" in first
    assert "repository_write; PCL domain state unchanged" in first
    assert "On failure: pcl next --target <goal_id> --json" in first
    skill_paths = [
        Path(".agents/skills/project-control-loop/SKILL.md"),
        Path("skills/project-control-loop/SKILL.md"),
        Path("plugins/codex-project-loop/skills/project-control-loop/SKILL.md"),
        Path("src/pcl/templates/skills/project-control-loop/SKILL.md"),
    ]
    skill_bytes = [path.read_bytes() for path in skill_paths]
    assert all(content == skill_bytes[0] for content in skill_bytes)
    skill = skill_bytes[0].decode("utf-8")
    assert "pcl guide --json" in skill
    assert "pcl guide <topic> --json" in skill


def test_operator_docs_define_permission_matrix_without_granting_authority() -> None:
    safety = Path("docs/safety-permissions.md").read_text(encoding="utf-8")
    guide = Path("docs/command-guide.md").read_text(encoding="utf-8")

    for authority_class in AUTHORITY_CLASSES:
        assert f"`{authority_class}`" in safety
    assert "does not grant authority" in safety
    assert "external or production write" in safety
    assert "human_decision_required" in guide
    assert "failure_recovery" in guide
    assert "healthy Evidence" in guide
