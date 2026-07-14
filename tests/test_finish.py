from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from pcl.cli import main
from pcl.contracts.completion_packet import load_completion_packet, validate_completion_packet
from pcl.db import connect
from pcl.finish_recovery import completion_packet_timeout_action
from pcl.outbox import ProjectionResult
from pcl.paths import resolve_paths
from pcl.route_overrides import override_route


COUNT_TABLES = [
    "goals",
    "workflow_runs",
    "agent_jobs",
    "verifications",
    "events",
    "evidence",
    "features",
    "user_stories",
    "test_cases",
    "defects",
]


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _create_run(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    assert main(["--root", str(root), "goal", "create", "--title", "Coverage"]) == 0
    assert main(["--root", str(root), "loop", "run", "feature_coverage", "--goal", "G-0001"]) == 0
    capsys.readouterr()


def _complete_jobs(root: Path, capsys) -> None:
    for job_id in ["J-0001", "J-0002", "J-0003"]:
        assert main([
            "--root",
            str(root),
            "jobs",
            "complete",
            job_id,
            "--summary",
            f"Completed {job_id}",
        ]) == 0
    capsys.readouterr()


def _approve_run(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "verification",
        "record",
        "--run",
        "WR-0001",
        "--result",
        "approved",
        "--reason",
        "Manual verification passed",
    ]) == 0
    capsys.readouterr()


def _complete_run(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "loop",
        "complete",
        "WR-0001",
        "--summary",
        "Workflow reviewed and completed",
    ]) == 0
    capsys.readouterr()


def _close_goal(root: Path, capsys) -> None:
    assert main([
        "--root",
        str(root),
        "goal",
        "close",
        "G-0001",
        "--summary",
        "Goal reviewed and closed",
        "--verification",
        "V-0001",
    ]) == 0
    capsys.readouterr()


def _state_counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in COUNT_TABLES
        }
    finally:
        conn.close()
    counts["events_jsonl"] = len((root / ".project-loop" / "events.jsonl").read_text(encoding="utf-8").splitlines())
    return counts


def _finish_payload(capsys) -> dict:
    payload = _json_output(capsys)
    assert payload["ok"] is True
    return payload["finish"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _create_packet_project(
    root: Path,
    capsys,
    *,
    failing: bool = False,
    with_change: bool = True,
    exhausted_budget: bool = False,
) -> None:
    assert main(["init", "--target", str(root)]) == 0
    config_path = root / "pcl.yaml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace('test: ""', 'test: "python -m pytest -q test_sample.py"')
    config_path.write_text(config, encoding="utf-8")
    test_path = root / "test_sample.py"
    test_path.write_text("def test_sample():\n    assert True\n", encoding="utf-8")
    gitignore = root / ".gitignore"
    gitignore.write_text(
        gitignore.read_text(encoding="utf-8") + "\n__pycache__/\n.pytest_cache/\n",
        encoding="utf-8",
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "pcl@example.test")
    _git(root, "config", "user.name", "PCL Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    goal_args: list[str] = []
    if exhausted_budget:
        assert main([
            "--root", str(root), "goal", "create", "--title", "Budgeted goal",
            "--budget-json", '{"exhausted": true}',
        ]) == 0
        goal_args = ["--goal", "G-0001"]
    assert main([
        "--root", str(root), "task", "create", "--title", "Finish packet task",
        "--description", "Exercise completion packet emission",
        *goal_args,
    ]) == 0
    assert main([
        "--root", str(root), "task", "status", "T-0001", "in_progress", "--reason", "Start work",
    ]) == 0
    if with_change:
        assertion = "False" if failing else "True"
        test_path.write_text(
            f"def test_sample():\n    assert {assertion}\n\n# completion packet change\n",
            encoding="utf-8",
        )
    capsys.readouterr()


def _evidence_count(root: Path, evidence_type: str) -> int:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return int(
            conn.execute("SELECT COUNT(*) FROM evidence WHERE type = ?", (evidence_type,)).fetchone()[0]
        )
    finally:
        conn.close()


def _record_fake_timeout(root: Path, command: dict, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "01-finish.stdout.txt"
    stderr_path = run_dir / "01-finish.stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("Timed out during test.\n", encoding="utf-8")
    command.update(
        {
            "exit_code": None,
            "status": "failed",
            "timed_out": True,
            "stdout_path": str(stdout_path.relative_to(root)),
            "stderr_path": str(stderr_path.relative_to(root)),
            "stdout": {"text": "", "path": str(stdout_path.relative_to(root))},
            "stderr": {
                "text": "Timed out during test.\n",
                "path": str(stderr_path.relative_to(root)),
            },
            "output_truncated": False,
            "redacted": False,
            "termination": {"reason": "timeout", "signal": "SIGTERM"},
            "failure_kind": "timeout",
            "permission_contract": {"backend": "test"},
        }
    )


def test_finish_plans_active_workflow_without_mutation(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["target"] == {"run": "WR-0001", "goal": "G-0001"}
    assert finish["finished"] is False
    assert finish["next_command"] == "pcl jobs read J-0001"
    assert finish["remaining_steps"] == [
        {
            "type": "continue_workflow",
            "command": "pcl jobs read J-0001",
            "reason": "A workflow run is already active and has queued or running jobs.",
            "requires_human": False,
            "safe_to_run": True,
        }
    ]
    assert _state_counts(tmp_path) == before

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    step = finish["remaining_steps"][0]
    assert step == {key: action[key] for key in step}


def test_finish_execute_with_pending_assertion_runs_nothing(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main(["--root", str(tmp_path), "finish", "--execute", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["finished"] is False
    assert finish["next_command"].startswith("pcl verification record --run WR-0001")
    assert finish["remaining_steps"][0]["type"] == "record_verification"
    assert finish["remaining_steps"][0]["requires_human"] is True
    assert finish["remaining_steps"][0]["safe_to_run"] is False
    assert finish["executed"] == []
    assert finish["changed"] is False
    assert _state_counts(tmp_path) == before


def test_finish_plans_goal_close_after_passed_run(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _approve_run(tmp_path, capsys)
    _complete_run(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["target"] == {"run": "WR-0001", "goal": "G-0001"}
    assert finish["finished"] is False
    assert finish["remaining_steps"] == [
        {
            "type": "close_goal",
            "command": "pcl goal close G-0001 --summary 'Summarize completed goal' --verification V-0001",
            "reason": "The workflow run has passed and its goal is still open.",
            "requires_human": True,
            "safe_to_run": False,
        }
    ]


def test_finish_execute_closed_loop_runs_generation_tail(tmp_path: Path, capsys) -> None:
    _create_run(tmp_path, capsys)
    _complete_jobs(tmp_path, capsys)
    _approve_run(tmp_path, capsys)
    _complete_run(tmp_path, capsys)
    _close_goal(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "finish", "--execute", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish["target"] == {"run": None, "goal": None}
    assert finish["finished"] is True
    assert finish["remaining_steps"] == []
    assert finish["next_command"] is None
    assert finish["executed"] == [
        {"command": "pcl validate --strict", "ok": True},
        {"command": "pcl render", "ok": True},
    ]
    assert finish["changed"] is True

    assert main(["--root", str(tmp_path), "finish", "--execute", "--json"]) == 0
    rerun = _finish_payload(capsys)
    assert rerun["finished"] is True
    assert rerun["remaining_steps"] == []
    assert rerun["executed"] == [
        {"command": "pcl validate --strict", "ok": True},
        {"command": "pcl render", "ok": True},
    ]


def test_finish_no_active_run_and_no_open_goal_is_finished(tmp_path: Path, capsys) -> None:
    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    finish = _finish_payload(capsys)

    assert finish == {
        "target": {"run": None, "goal": None},
        "finished": True,
        "remaining_steps": [],
        "next_command": None,
    }


def test_finish_help_and_plan_only_json_contract_remain_backward_compatible(
    tmp_path: Path, capsys
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["finish", "--help"])
    assert exc_info.value.code == 0
    help_output = capsys.readouterr().out
    assert "usage: pcl finish" in help_output
    assert "--execute" in help_output
    assert "--run RUN" in help_output
    assert "--goal GOAL" in help_output

    assert main(["init", "--target", str(tmp_path)]) == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "finish", "--json"]) == 0
    assert _finish_payload(capsys) == {
        "target": {"run": None, "goal": None},
        "finished": True,
        "remaining_steps": [],
        "next_command": None,
    }


def test_finish_emit_packet_dry_run_plans_without_mutation(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--dry-run", "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)

    assert finish["mode"] == "emit_packet"
    assert finish["dry_run"] is True
    assert finish["target"]["id"] == "T-0001"
    assert finish["check_plan"] == [
        {
            "id": "finish_checks:1",
            "config_key": "test",
            "command": "python -m pytest -q test_sample.py",
            "safe_to_run": True,
            "blocked_reason": "",
        }
    ]
    assert finish["safe_to_execute"] is True
    assert _state_counts(tmp_path) == before


def test_finish_emit_packet_success_and_idempotent_rerun(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys)

    command = [
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]
    assert main(command) == 0
    finish = _finish_payload(capsys)

    assert finish["packet"]["outcome"] == "COMPLETED_VERIFIED"
    assert finish["target_transition"] == {
        "changed": True,
        "from_status": "in_progress",
        "to_status": "done",
    }
    assert finish["checks"][0]["status"] == "passed"
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert validate_completion_packet(packet).ok is True
    assert packet["repository"]["diff_sha256"] == finish["repository"]["diff_sha256"]
    assert packet["checks"][0]["artifact_ref"] == f"evidence:{finish['checks'][0]['evidence_id']}"
    before = _state_counts(tmp_path)

    assert main(command) == 0
    rerun = _finish_payload(capsys)
    assert rerun["idempotent"] is True
    assert rerun["changed"] is False
    assert rerun["packet"] == finish["packet"]
    assert _state_counts(tmp_path) == before


def test_finish_emit_packet_failure_keeps_task_active(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys, failing=True)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 1
    finish = _finish_payload(capsys)

    assert finish["packet"]["outcome"] == "INCOMPLETE_VALIDATION"
    assert finish["checks"][0]["status"] == "failed"
    assert finish["target_transition"]["changed"] is False
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute("SELECT status FROM tasks WHERE id = 'T-0001'").fetchone()[0] == "in_progress"
    finally:
        conn.close()


def test_finish_timeout_exposes_bounded_retry_and_next_preserves_it(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _create_packet_project(tmp_path, capsys)

    def fake_timeout(paths, command, *, run_dir, **kwargs):
        _record_fake_timeout(paths.root, command, run_dir)

    monkeypatch.setattr(
        "pcl.finish_execution.execute_planned_guarded_command",
        fake_timeout,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 1
    finish = _finish_payload(capsys)
    expected = "pcl finish --emit-packet --task T-0001 --timeout 600 --json"
    assert finish["checks"][0]["status"] == "timed_out"
    assert finish["timeout_recovery"] == {
        "available": True,
        "reason": "finish_check_timed_out",
        "timed_out_evidence_id": finish["checks"][0]["evidence_id"],
        "previous_timeout_seconds": 120,
        "suggested_timeout_seconds": 600,
        "retry_command": expected,
        "diagnostic_command": (
            f"pcl evidence show {finish['checks'][0]['evidence_id']} --json"
        ),
    }
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["next_action"]["command"] == expected
    packet["next_action"]["command"] = "pcl finish --emit-packet --task T-9999 --timeout 600 --json"
    assert completion_packet_timeout_action(packet) is None

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "retry_finish_timeout"
    assert action["command"] == expected
    assert action["run_policy"] == "agent_safe"
    assert action["requires_human"] is False
    assert action["safe_to_run"] is True


def test_finish_timeout_at_limit_routes_to_evidence_diagnosis(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _create_packet_project(tmp_path, capsys)

    def fake_timeout(paths, command, *, run_dir, **kwargs):
        _record_fake_timeout(paths.root, command, run_dir)

    monkeypatch.setattr(
        "pcl.finish_execution.execute_planned_guarded_command",
        fake_timeout,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001",
        "--timeout", "600", "--json",
    ]) == 1
    finish = _finish_payload(capsys)
    evidence_id = finish["checks"][0]["evidence_id"]
    diagnostic = f"pcl evidence show {evidence_id} --json"
    assert finish["timeout_recovery"] == {
        "available": False,
        "reason": "finish_timeout_limit_reached",
        "timed_out_evidence_id": evidence_id,
        "previous_timeout_seconds": 600,
        "suggested_timeout_seconds": None,
        "retry_command": None,
        "diagnostic_command": diagnostic,
    }
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["next_action"]["command"] == diagnostic
    assert "--timeout 600" not in packet["next_action"]["command"]

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] == "diagnose_finish_timeout"
    assert action["command"] == diagnostic
    assert action["blocking"] is True
    assert action["requires_human"] is False


def test_newer_non_timeout_packet_suppresses_stale_timeout_recovery(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _create_packet_project(tmp_path, capsys)

    def fake_timeout(paths, command, *, run_dir, **kwargs):
        _record_fake_timeout(paths.root, command, run_dir)

    monkeypatch.setattr(
        "pcl.finish_execution.execute_planned_guarded_command",
        fake_timeout,
    )
    finish_command = [
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]
    assert main(finish_command) == 1
    _finish_payload(capsys)

    monkeypatch.undo()
    (tmp_path / "test_sample.py").write_text(
        "def test_sample():\n    assert False\n\n# newer ordinary failure\n",
        encoding="utf-8",
    )
    assert main(finish_command) == 1
    newer = _finish_payload(capsys)
    assert newer["checks"][0]["status"] == "failed"
    assert "timeout_recovery" not in newer

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json_output(capsys)
    assert action["type"] not in {"retry_finish_timeout", "diagnose_finish_timeout"}


def test_finish_rejects_fail_open_missing_path_check_before_execution(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _create_packet_project(tmp_path, capsys)
    config_path = tmp_path / "pcl.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'test: "python -m pytest -q test_sample.py"',
            'test: "test -e work/site || echo missing implementation"',
        ),
        encoding="utf-8",
    )

    def unexpected_execution(*args, **kwargs):
        pytest.fail("blocked fail-open check was executed")

    monkeypatch.setattr(
        "pcl.finish_execution.execute_planned_guarded_command",
        unexpected_execution,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 2
    payload = _json_output(capsys)
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["blocked_checks"] == [
        {
            "id": "finish_checks:1",
            "config_key": "test",
            "command": "test -e work/site || echo missing implementation",
            "safe_to_run": False,
            "blocked_reason": "fail_open_check_command",
        }
    ]
    assert _evidence_count(tmp_path, "completion_check") == 0
    assert _evidence_count(tmp_path, "completion_packet") == 0
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        status = conn.execute("SELECT status FROM tasks WHERE id = 'T-0001'").fetchone()[0]
    finally:
        conn.close()
    assert status == "in_progress"


def test_finish_emit_packet_no_changes_keeps_task_active(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys, with_change=False)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)

    assert finish["packet"]["outcome"] == "NO_CHANGES"
    assert finish["target_transition"]["changed"] is False
    assert finish["packet"]["path"].endswith(".json")


def test_finish_detects_repository_change_during_checks(tmp_path: Path, capsys, monkeypatch) -> None:
    _create_packet_project(tmp_path, capsys)
    from pcl import finish_execution

    execute = finish_execution.execute_planned_guarded_command

    def execute_and_mutate(*args, **kwargs):
        execute(*args, **kwargs)
        path = tmp_path / "test_sample.py"
        path.write_text(path.read_text(encoding="utf-8") + "# raced\n", encoding="utf-8")

    monkeypatch.setattr(finish_execution, "execute_planned_guarded_command", execute_and_mutate)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 1
    finish = _finish_payload(capsys)
    assert finish["race_detected"] is True
    assert finish["packet"]["outcome"] == "INCOMPLETE_VALIDATION"
    assert finish["target_transition"]["changed"] is False


def test_finish_human_gate_emits_incomplete_packet_and_next_action(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys)
    assert main([
        "--root", str(tmp_path), "decision", "open",
        "--question", "May this task close?", "--recommendation", "Review Evidence",
        "--blocks-json", '[{"type":"task","id":"T-0001"}]',
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)
    assert finish["packet"]["outcome"] == "INCOMPLETE_HUMAN_DECISION_REQUIRED"
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["human_decisions"] == ["May this task close?"]
    assert packet["next_action"]["command"] == "pcl decision list --status open"
    assert finish["target_transition"]["changed"] is False


def test_finish_budget_block_emits_incomplete_packet(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys, exhausted_budget=True)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)
    assert finish["packet"]["outcome"] == "INCOMPLETE_BUDGET_EXHAUSTED"
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["next_action"]["command"] is None
    assert finish["target_transition"]["changed"] is False


def test_finish_projector_failure_reports_committed_packet_without_duplicate(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _create_packet_project(tmp_path, capsys)
    from pcl import outbox

    def pending_projection(*args, **kwargs):
        return ProjectionResult(
            committed=True,
            projection="pending",
            delivered=0,
            pending_count=1,
            first_pending_sequence=1,
            safe_next_action="Run `pcl audit flush --json`; do not retry the committed mutation.",
            error="injected projector failure",
        )

    monkeypatch.setattr(outbox, "project_pending_events", pending_projection)
    command = [
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]
    assert main(command) == 6
    error = _json_output(capsys)
    assert error["error"]["code"] == "audit_projection_pending"
    assert _evidence_count(tmp_path, "completion_packet") == 1

    monkeypatch.undo()
    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 0
    capsys.readouterr()
    assert main(command) == 0
    rerun = _finish_payload(capsys)
    assert rerun["idempotent"] is True
    assert _evidence_count(tmp_path, "completion_packet") == 1


def test_finish_packet_includes_recorded_adaptive_route(tmp_path: Path, capsys) -> None:
    _create_packet_project(tmp_path, capsys)
    applied = override_route(
        resolve_paths(tmp_path),
        target_ref="task:T-0001",
        requested_profile="assure",
        actor="human:test-owner",
        reason="Completion packet integration fixture",
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])

    assert packet["adaptive_route"]["override_ref"] == (
        f"evidence:{applied['evidence']['override']['id']}"
    )
    assert packet["adaptive_route"]["effective_profile"] == "assure"
    assert validate_completion_packet(packet).ok is True
