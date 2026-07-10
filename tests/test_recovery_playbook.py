from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_recovery_playbook_documents_guardrails() -> None:
    playbook = Path("docs/recovery-playbook.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    golden_path = Path("docs/golden-path.md").read_text(encoding="utf-8")

    for required in [
        "pcl validate --strict --json",
        "pcl report validation --strict",
        "pcl next --strict --json",
        "pcl loop status --json",
        "Do not edit `.project-loop/project.db` directly.",
        "Do not edit `.project-loop/events.jsonl` directly.",
        "pcl escalation open",
        "pcl repair lifecycle --dry-run --json",
        "lifecycle-repair-plan/v1",
        "There is no lifecycle repair `--apply` mode.",
    ]:
        assert required in playbook

    assert "docs/recovery-playbook.md" in readme
    assert "recovery-playbook.md" in golden_path


def test_recovery_playbook_validation_commands_stay_current(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main(["--root", str(tmp_path), "loop", "run", "regression_loop", "--goal", "G-0001"]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "next", "--strict", "--json"]) == 0
    next_action = _json_output(capsys)
    assert next_action["type"] == "resolve_validation_errors"
    assert next_action["command"] == "pcl report validation --strict"
    assert next_action["blocking"] is True
    assert next_action["requires_human"] is True

    assert main(["--root", str(tmp_path), "report", "validation", "--strict", "--json"]) == 0
    payload = _json_output(capsys)
    report_path = Path(payload["path"])
    report = report_path.read_text(encoding="utf-8")

    assert payload["kind"] == "validation"
    assert payload["report"]["strict"] is True
    assert payload["report"]["ok"] is False
    assert report_path == tmp_path / ".project-loop" / "reports" / "validation-strict.md"
    assert "Duplicate active workflow runs for goal G-0001: WR-0001, WR-0002." in report
    assert "manual review" in report
