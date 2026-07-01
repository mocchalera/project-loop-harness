from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_duplicate_active_runs(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    assert main(["--root", str(root), "loop", "run", "regression_loop", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def test_next_strict_routes_validation_errors_before_normal_next_action(tmp_path: Path, capsys) -> None:
    _create_duplicate_active_runs(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    normal = _json_output(capsys)
    assert normal["type"] == "continue_workflow"

    assert main(["--root", str(tmp_path), "next", "--strict", "--json"]) == 0
    strict = _json_output(capsys)
    assert strict["type"] == "resolve_validation_errors"
    assert strict["command"] == "pcl report validation --strict"
    assert strict["target"]["strict"] is True
    assert "Duplicate active workflow runs for goal G-0001: WR-0001, WR-0002." in strict["target"]["errors"]


def test_report_validation_strict_writes_diagnostics(tmp_path: Path, capsys) -> None:
    _create_duplicate_active_runs(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "report", "validation", "--strict", "--json"]) == 0
    payload = _json_output(capsys)
    report_path = Path(payload["path"])
    markdown = report_path.read_text(encoding="utf-8")

    assert payload["kind"] == "validation"
    assert payload["report"]["strict"] is True
    assert payload["report"]["ok"] is False
    assert report_path == tmp_path / ".project-loop" / "reports" / "validation-strict.md"
    assert "# Validation Report" in markdown
    assert "Duplicate active workflow runs for goal G-0001: WR-0001, WR-0002." in markdown
    assert "pcl validate --strict --json" in markdown
    assert "manual review" in markdown


def test_report_validation_current_passes_for_normal_project(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "report", "validation", "--json"]) == 0
    payload = _json_output(capsys)
    report_path = Path(payload["path"])

    assert payload["report"]["strict"] is False
    assert payload["report"]["ok"] is True
    assert payload["report"]["errors"] == []
    assert payload["report"]["warnings"] == []
    assert report_path == tmp_path / ".project-loop" / "reports" / "validation.md"
    assert "Validation passed; continue the project loop." in report_path.read_text(encoding="utf-8")
