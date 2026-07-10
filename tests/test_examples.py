from __future__ import annotations

import json
import shutil
from pathlib import Path

from pcl.cli import main
from pcl.workflow_yaml import parse_workflow_yaml


EXAMPLES = [
    Path("examples/python-cli"),
    Path("examples/nextjs"),
]


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_example_configs_have_current_guardrails() -> None:
    for example in EXAMPLES:
        config = parse_workflow_yaml((example / "pcl.yaml").read_text(encoding="utf-8"))

        assert config["project_loop"]["version"] == "0.1.0"
        assert config["project_loop"]["schema_version"] == 3
        assert config["loop"]["lease_ttl_seconds"] == 1800
        assert config["loop"]["max_lease_attempts"] == 2
        assert config["loop"]["stop_if_same_failure_repeats"] is True
        assert config["dashboard"]["output"] == ".project-loop/dashboard/dashboard.html"
        assert config["dashboard"]["auto_render"] is True
        assert ".project-loop/project.db" in config["permissions"]["agent_may_not_modify"]
        assert ".project-loop/events.jsonl" in config["permissions"]["agent_may_not_modify"]
        assert "destructive_operation" in config["permissions"]["require_human_approval"]


def test_example_docs_point_to_current_operator_flow() -> None:
    examples_readme = Path("examples/README.md").read_text(encoding="utf-8")
    assert "pcl next --root /tmp/pcl-python-cli-example --json" in examples_readme
    assert "docs/golden-path.md" in examples_readme
    assert "docs/recovery-playbook.md" in examples_readme

    for example in EXAMPLES:
        readme = (example / "README.md").read_text(encoding="utf-8")
        assert "pcl validate --root" in readme
        assert "--strict --json" in readme
        assert "pcl next --root" in readme
        assert "docs/recovery-playbook.md" in readme


def test_examples_can_be_initialized_validated_and_rendered(tmp_path: Path, capsys) -> None:
    for example in EXAMPLES:
        target = tmp_path / example.name
        shutil.copytree(example, target)
        original_config = (target / "pcl.yaml").read_text(encoding="utf-8")

        assert main(["init", "--target", str(target), "--json"]) == 0
        init_payload = _json_output(capsys)
        assert init_payload["created"] is True
        assert (target / "pcl.yaml").read_text(encoding="utf-8") == original_config

        assert main(["--root", str(target), "validate", "--strict", "--json"]) == 0
        assert _json_output(capsys)["ok"] is True

        assert main(["--root", str(target), "render", "--json"]) == 0
        render = _json_output(capsys)
        assert Path(render["path"]).exists()

        assert main(["--root", str(target), "next", "--json"]) == 0
        next_action = _json_output(capsys)
        assert next_action["type"] == "idle"
        assert next_action["command"] is None
        assert next_action["requires_human"] is False
