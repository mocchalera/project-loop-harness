from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.evidence import (
    EvidenceAddError,
    assess_adhoc_evidence,
    require_healthy_terminal_evidence,
)
from pcl.paths import resolve_paths
from pcl.workflow_sandbox import plan_guarded_project_checks


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)


def _set_commands(root: Path, body: str) -> None:
    config = root / "pcl.yaml"
    before = config.read_text(encoding="utf-8")
    prefix, _, suffix = before.partition("commands:\n")
    _, separator, remainder = suffix.partition("\ndiscovery:\n")
    assert separator
    config.write_text(prefix + "commands:\n" + body + "\ndiscovery:\n" + remainder, encoding="utf-8")


def test_finish_check_bootstrap_is_early_actionable_and_typed(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "start", "Write instructions", "--json"]) == 0
    started = _json_output(capsys)
    assert len(started["warnings"]) == 1
    assert "No enabled finish checks" in started["warnings"][0]
    assert 'test: "python -m pytest"' in started["warnings"][0]

    assert main(["--root", str(tmp_path), "doctor", "--strict", "--json"]) == 1
    doctor = _json_output(capsys)
    assert any(item["code"] == "config_finish_checks_missing" for item in doctor["findings"])

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 2
    error = _json_output(capsys)["error"]
    assert error["code"] == "finish_checks_not_configured"
    assert error["details"]["failure_kind"] == "configuration_missing"
    assert error["details"]["next_command"] == "pcl doctor --json"


def test_disabled_commands_are_intentional_and_exact_git_diff_check_is_safe(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    _set_commands(
        tmp_path,
        '  lint: "git diff --check"\n'
        "  typecheck: null\n"
        '  test: "python -m pytest"\n'
        "  e2e:\n"
        "    disabled: true\n"
        "  build: {disabled: true}\n",
    )

    assert main(["--root", str(tmp_path), "doctor", "--strict", "--json"]) == 1
    doctor = _json_output(capsys)
    assert not any(item["code"] == "config_commands_empty" for item in doctor["findings"])
    assert not any(item["code"] == "config_finish_checks_missing" for item in doctor["findings"])

    paths = resolve_paths(tmp_path)
    planned = plan_guarded_project_checks(paths)
    assert [item["raw_command"] for item in planned] == [
        "project.commands.lint",
        "project.commands.test",
    ]
    assert planned[0]["argv"] == ["git", "diff", "--check"]
    assert planned[0]["safe_to_run"] is True

    _set_commands(tmp_path, '  lint: "git diff --check HEAD"\n')
    blocked = plan_guarded_project_checks(paths)[0]
    assert blocked["safe_to_run"] is False
    assert blocked["blocked_reason"] == "project command executable is blocked: git"


def test_copied_outside_evidence_is_healthy_after_source_disappears_and_can_be_superseder(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    old = tmp_path / "old.txt"
    old.write_text("old\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", "old.txt",
        "--summary", "old proof", "--json",
    ]) == 0
    old_evidence = _json_output(capsys)["evidence"]
    old.write_text("drifted\n", encoding="utf-8")

    outside = tmp_path.parent / f"{tmp_path.name}-proof.txt"
    outside.write_text("canonical proof\n", encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", str(outside),
        "--summary", "copied proof", "--copy", "--json",
    ]) == 0
    replacement = _json_output(capsys)["evidence"]
    outside.unlink()

    paths = resolve_paths(tmp_path)
    assessment = assess_adhoc_evidence(
        paths,
        evidence_id=replacement["id"],
        evidence_type=replacement["type"],
        manifest_path_value=replacement["manifest_path"],
        validate_optional_fields=True,
    )
    assert assessment["health"] == "ok"
    assert assessment["findings"] == [
        {"code": "source_drifted", "path": replacement["members"][0]["path"], "detail": "missing"}
    ]

    assert main([
        "--root", str(tmp_path), "evidence", "supersede", old_evidence["id"],
        "--with", replacement["id"], "--summary", "replace drifted proof", "--json",
    ]) == 0
    superseded = _json_output(capsys)
    assert superseded["changed"] is True

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    validation = _json_output(capsys)
    assert not any(old_evidence["id"] in warning for warning in validation["warnings"])

    assert main([
        "--root", str(tmp_path), "evidence", "show", old_evidence["id"], "--json",
    ]) == 0
    assert _json_output(capsys)["evidence"]["superseded_by"] == replacement["id"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        with pytest.raises(EvidenceAddError) as exc_info:
            require_healthy_terminal_evidence(
                paths,
                conn,
                evidence_id=old_evidence["id"],
                error_code="terminal_evidence_invalid",
            )
        assert exc_info.value.details["reason"] == "evidence_superseded"
        require_healthy_terminal_evidence(
            paths,
            conn,
            evidence_id=replacement["id"],
            error_code="terminal_evidence_invalid",
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("configured", "expected_type", "expected_command"),
    [
        (True, "emit_completion_packet", "pcl finish --emit-packet --goal G-0001 --json"),
        (False, "configure_finish_checks", "pcl doctor --json"),
    ],
)
def test_next_prefers_direct_finish_for_terminal_goal(
    tmp_path: Path,
    capsys,
    configured: bool,
    expected_type: str,
    expected_command: str,
) -> None:
    _init(tmp_path, capsys)
    if configured:
        _set_commands(tmp_path, '  test: "python -m pytest"\n')
    assert main(["--root", str(tmp_path), "start", "Direct work", "--json"]) == 0
    _json_output(capsys)
    assert main([
        "--root", str(tmp_path), "task", "status", "T-0001", "done", "--reason", "done", "--json",
    ]) == 0
    _json_output(capsys)

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == expected_type
    assert action["command"] == expected_command
    assert "feature_coverage" not in action["command"]


def test_finish_snapshot_separates_harness_local_state(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _set_commands(tmp_path, '  test: "python -m pytest"\n')
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "pcl@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "PCL Test"], cwd=tmp_path, check=True)
    (tmp_path / "source.txt").write_text("baseline\n", encoding="utf-8")
    marker = tmp_path / ".project-loop" / "runtime-marker.txt"
    marker.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-f", ".project-loop/runtime-marker.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True)
    assert main(["--root", str(tmp_path), "task", "create", "--title", "snapshot", "--json"]) == 0
    _json_output(capsys)
    marker.write_text("changed\n", encoding="utf-8")

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--dry-run", "--task", "T-0001", "--json",
    ]) == 0
    finish = _json_output(capsys)["finish"]
    assert finish["repository"]["dirty"] is False
    assert finish["changes"] == []
    assert finish["harness_local_state"] == [
        {"change_type": "modified", "path": ".project-loop/runtime-marker.txt", "previous_path": None}
    ]


def test_feature_add_can_atomically_link_existing_task(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "task", "create", "--title", "linked", "--json"]) == 0
    _json_output(capsys)
    assert main([
        "--root", str(tmp_path), "feature", "add", "--name", "Linked feature",
        "--surface", "cli:test", "--task", "T-0001", "--json",
    ]) == 0
    assert _json_output(capsys)["id"] == "F-0001"
    assert main(["--root", str(tmp_path), "task", "read", "T-0001", "--json"]) == 0
    assert _json_output(capsys)["task"]["related_feature_id"] == "F-0001"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        events = conn.execute(
            "SELECT event_type FROM events WHERE entity_id = 'T-0001' ORDER BY sequence"
        ).fetchall()
        assert [str(row["event_type"]) for row in events][-1] == "task_feature_linked"
        before = int(conn.execute("SELECT COUNT(*) FROM features").fetchone()[0])
    finally:
        conn.close()
    assert main([
        "--root", str(tmp_path), "feature", "add", "--name", "Conflict",
        "--surface", "cli:conflict", "--task", "T-0001", "--json",
    ]) == 2
    _json_output(capsys)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert int(conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]) == before
    finally:
        conn.close()
