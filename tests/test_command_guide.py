from __future__ import annotations

import json
from pathlib import Path
import re
import shlex

from pcl.cli import _extract_global_options, build_parser, main
from pcl.command_guide import command_guide


TOPICS = ["start", "direct", "finish", "dashboard", "recover"]
STEP_KEYS = {
    "order",
    "command",
    "mutates_state",
    "run_policy",
    "requires",
    "purpose",
    "expected_after",
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
