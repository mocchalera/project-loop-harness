from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from pcl import finish_output
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


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for item in value.values()
            for key in _nested_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _nested_keys(item)}
    return set()


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


def _terminal_artifact_snapshot(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        task = dict(conn.execute("SELECT * FROM tasks WHERE id = 'T-0001'").fetchone())
        events = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, sequence, event_type, entity_type, entity_id,
                       payload_json, created_at
                FROM events
                ORDER BY sequence
                """
            ).fetchall()
        ]
        outbox = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, event_id, sink, idempotency_key, status, attempts,
                       next_attempt_at, last_error, created_at, updated_at,
                       delivered_at
                FROM outbox_records
                ORDER BY id
                """
            ).fetchall()
        ]
        completion_evidence = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, type, path, command, summary, created_at
                FROM evidence
                WHERE type IN ('completion_check', 'completion_packet')
                ORDER BY id
                """
            ).fetchall()
        ]
    finally:
        conn.close()
    dashboard = root / ".project-loop" / "dashboard"
    packet_dir = root / ".project-loop" / "evidence" / "completion-packets"
    return {
        "task": task,
        "events": events,
        "outbox": outbox,
        "completion_evidence": completion_evidence,
        "events_jsonl": (root / ".project-loop" / "events.jsonl").read_bytes(),
        "dashboard_html": (dashboard / "dashboard.html").read_bytes(),
        "dashboard_data": (dashboard / "dashboard-data.json").read_bytes(),
        "packets": {
            path.name: path.read_bytes()
            for path in sorted(packet_dir.glob("*"))
            if path.is_file()
        }
        if packet_dir.exists()
        else {},
    }


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


def _configure_finish_command(root: Path, key: str, command: str) -> None:
    config_path = root / "pcl.yaml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace(f'{key}: ""', f'{key}: "{command}"')
    config_path.write_text(config, encoding="utf-8")


def _finish_command_key(command: dict) -> str:
    return str(command["raw_command"]).removeprefix("project.commands.")


def _open_task_decision(root: Path, capsys) -> None:
    assert main([
        "--root", str(root), "decision", "open",
        "--question", "May this task close?", "--recommendation", "Review Evidence",
        "--blocks-json", '[{"type":"task","id":"T-0001"}]',
    ]) == 0
    capsys.readouterr()


def _latest_check_anchor(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type = 'completion_packet_created'
            ORDER BY sequence DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return json.loads(str(row["payload_json"]))


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


def test_finish_task_dry_run_uses_shared_target_binding_and_readiness(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--dry-run",
        "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)
    assert finish["target"]["id"] == "T-0001"
    assert finish["target"]["goal_id"] is None
    assert finish["target_binding"] == {
        "target_type": "task",
        "target_id": "T-0001",
        "source": "explicit",
    }
    assert finish["terminal_readiness"]["contract_version"] == "terminal-readiness/v1"


def test_finish_output_projection_summary_and_page_bound_display_without_weakening_snapshot(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)
    claude_state = tmp_path / ".claude" / "state"
    claude_state.mkdir(parents=True)
    (claude_state / "session.json").write_text('{"noise": true}\n', encoding="utf-8")
    work_state = tmp_path / ".work"
    work_state.mkdir()
    (work_state / "trace.txt").write_text("local trace\n", encoding="utf-8")
    command = [
        "--root", str(tmp_path), "finish", "--emit-packet", "--dry-run",
        "--task", "T-0001",
    ]

    assert main([*command, "--json"]) == 0
    full = _finish_payload(capsys)
    full_keys = set(full)
    assert "output_projection" not in full
    machine_changes = [
        item
        for item in full["changes"]
        if item["path"].startswith((".claude/", ".work/"))
    ]
    assert len(machine_changes) == 2

    assert main([
        *command,
        "--summary",
        "--exclude-machine-state",
        "--json",
    ]) == 0
    summary = _finish_payload(capsys)
    projection = summary["output_projection"]

    assert set(summary) == full_keys | {"output_projection"}
    assert summary["changes"] == []
    assert summary["harness_local_state"] == []
    assert summary["repository"] == full["repository"]
    assert projection["contract_version"] == "finish-output-projection/v1"
    assert projection["mode"] == "summary"
    assert projection["repository_snapshot"] == {
        "scope": "complete",
        "dirty": full["repository"]["dirty"],
        "diff_sha256": full["repository"]["diff_sha256"],
    }
    assert projection["machine_state"]["excluded_from_display"] is True
    assert projection["machine_state"]["omitted_count"] == 2
    assert projection["machine_state"]["omitted_by_prefix"] == {
        ".claude/": 1,
        ".work/": 1,
    }
    assert projection["sections"]["changes"]["total_count"] == len(full["changes"])
    assert projection["sections"]["changes"]["eligible_count"] == (
        len(full["changes"]) - 2
    )
    assert projection["sections"]["changes"]["returned_count"] == 0
    assert projection["sections"]["harness_local_state"]["total_count"] == len(
        full["harness_local_state"]
    )

    assert main([
        *command,
        "--output-offset", "0",
        "--output-limit", "1",
        "--exclude-machine-state",
        "--json",
    ]) == 0
    page = _finish_payload(capsys)
    eligible_changes = [
        item
        for item in full["changes"]
        if not item["path"].startswith((".claude/", ".work/"))
    ]
    assert page["changes"] == eligible_changes[:1]
    assert page["harness_local_state"] == full["harness_local_state"][:1]
    assert page["repository"] == full["repository"]
    assert page["output_projection"]["mode"] == "page"
    assert page["output_projection"]["pagination"] == {
        "offset": 0,
        "limit": 1,
    }
    assert page["output_projection"]["sections"]["changes"]["returned_count"] == (
        min(1, len(eligible_changes))
    )


@pytest.mark.parametrize(
    "extra",
    [
        ["--summary", "--output-limit", "1"],
        ["--dry-run", "--summary", "--output-limit", "1"],
        ["--dry-run", "--output-limit", "0"],
        ["--dry-run", "--output-offset", "-1"],
    ],
)
def test_finish_output_projection_flags_fail_closed_without_mutation(
    tmp_path: Path,
    capsys,
    extra: list[str],
) -> None:
    _create_packet_project(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", *extra, "--json",
    ]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert _state_counts(tmp_path) == before


def test_finish_actual_summary_is_compact_and_preserves_durable_proof(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)
    claude_state = tmp_path / ".claude" / "state"
    claude_state.mkdir(parents=True)
    (claude_state / "session.json").write_text('{"noise": true}\n', encoding="utf-8")
    work_state = tmp_path / ".work"
    work_state.mkdir()
    (work_state / "trace.txt").write_text("local trace\n", encoding="utf-8")

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--summary", "--exclude-machine-state", "--json",
    ]) == 0
    finish = _finish_payload(capsys)

    assert finish["target_binding"] == {
        "target_type": "task",
        "target_id": "T-0001",
        "source": "explicit",
    }
    assert finish["repository"]["diff_sha256"].startswith("sha256:")
    assert finish["changes"] == []
    assert finish["harness_local_state"] == []
    assert finish["packet"]["outcome"] == "COMPLETED_VERIFIED"
    assert finish["target_transition"]["to_status"] == "done"
    assert finish["terminal_readiness"]["contract_version"] == (
        "terminal-readiness/v1"
    )
    assert finish["terminal_readiness"]["terminal_allowed"] is True
    assert finish["strict_validation"]["ok"] is True
    assert finish["strict_validation"]["warning_count"] >= 0
    assert finish["execution"]["effect"]["classification"] == "declared_outputs"

    check = finish["checks"][0]
    assert check["contract_version"] == "finish-check-result/v2"
    assert check["evidence_id"].startswith("E-")
    assert check["artifact_sha256"].startswith("sha256:")
    assert check["status"] == "passed"
    assert check["runner_status"] == "completed"
    assert check["assertion_status"] == "passed"
    assert check["attempt_identity_sha256"].startswith("sha256:")
    assert check["execution_identity_sha256"].startswith("sha256:")
    assert "command" not in check
    assert "stdout" not in check
    assert "stderr" not in check
    assert "permission_contract" not in check

    projection = finish["output_projection"]
    assert projection["contract_version"] == "finish-output-projection/v1"
    assert projection["source_mode"] == "actual"
    assert projection["mode"] == "summary"
    assert projection["repository_snapshot"]["diff_sha256"] == (
        finish["repository"]["diff_sha256"]
    )
    assert projection["machine_state"]["omitted_count"] == 2
    assert projection["sections"]["checks"]["total_count"] == 1
    assert projection["sections"]["checks"]["returned_count"] == 1

    check_evidence = json.loads(
        (
            tmp_path
            / ".project-loop"
            / "evidence"
            / "completion-checks"
            / check["evidence_id"]
            / "result.json"
        ).read_text(encoding="utf-8")
    )
    assert check_evidence["command"] == "python -m pytest -q test_sample.py"
    assert check_evidence["permission_contract"]["backend"] == "host_subprocess"
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["repository"]["diff_sha256"] == finish["repository"]["diff_sha256"]
    assert packet["checks"][0]["artifact_ref"] == f"evidence:{check['evidence_id']}"
    assert len(json.dumps(finish, ensure_ascii=False).encode("utf-8")) <= 16_384


def test_finish_actual_projection_is_presentation_only(
    tmp_path: Path,
    capsys,
) -> None:
    full_root = tmp_path / "full"
    projected_root = tmp_path / "projected"
    _create_packet_project(full_root, capsys)
    _create_packet_project(projected_root, capsys)

    assert main([
        "--root", str(full_root), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]) == 0
    full = _finish_payload(capsys)
    assert "output_projection" not in full
    full_counts = _state_counts(full_root)

    assert main([
        "--root", str(projected_root), "finish", "--emit-packet",
        "--task", "T-0001", "--summary", "--json",
    ]) == 0
    projected = _finish_payload(capsys)
    projected_counts = _state_counts(projected_root)

    assert projected_counts == full_counts
    assert projected["packet"]["outcome"] == full["packet"]["outcome"]
    assert projected["target_transition"] == full["target_transition"]
    assert projected["repository"]["diff_sha256"] == full["repository"]["diff_sha256"]
    assert projected["checks"][0]["evidence_id"] == full["checks"][0]["evidence_id"]
    assert projected["output_projection"]["source_mode"] == "actual"


def test_finish_actual_summary_bounds_large_nested_sections() -> None:
    changes = [
        {
            "path": f".claude/state/{index:04d}.json"
            if index % 2
            else f"src/generated_{index:04d}.py",
            "status": "modified",
        }
        for index in range(500)
    ]
    warnings = [f"repeated warning {index % 5}" for index in range(200)]
    effect_changes = [
        {"path": f"build/output-{index:04d}.txt", "change": "added"}
        for index in range(200)
    ]
    readiness_reasons = [
        {
            "code": f"reason_{index % 4}",
            "state": "risk",
            "requires_human": False,
            "next_command": f"pcl test read TC-{index % 4:04d} --json",
        }
        for index in range(200)
    ]
    result = {
        "mode": "emit_packet",
        "dry_run": False,
        "target": {"type": "task", "id": "T-0001", "status": "in_progress"},
        "target_binding": {
            "target_type": "task",
            "target_id": "T-0001",
            "source": "explicit",
        },
        "repository": {
            "base_revision": "base",
            "head_revision": "head",
            "dirty": True,
            "diff_sha256": "sha256:" + "a" * 64,
        },
        "changes": changes,
        "harness_local_state": changes[:100],
        "checks": [{
            "contract_version": "finish-check-result/v2",
            "evidence_id": "E-0001",
            "artifact_sha256": "sha256:" + "b" * 64,
            "command": "python -m pytest",
            "status": "passed",
            "exit_code": 0,
            "failure_phase": None,
            "failure_kind": None,
            "runner_result": {"status": "completed"},
            "assertion_result": {"status": "passed"},
            "stdout": {"text": "large output" * 100},
            "stderr": {"text": ""},
            "permission_contract": {"environment": {"values": ["secret"]}},
            "output_truncated": False,
            "redacted": False,
            "attempt_identity": {
                "identity_sha256": "sha256:" + "c" * 64,
                "execution_identity_sha256": "sha256:" + "d" * 64,
            },
            "stability_evaluation": {
                "status": "reproducible",
                "reproducible": True,
                "attempt_count": 2,
                "remaining_attempts": 1,
            },
            "reuse": {
                "status": "executed",
                "reused_role_count": 0,
                "role_bindings": [{"config_key": "test"}],
                "compatible_history": list(range(200)),
            },
        }],
        "execution": {
            "workspace": {
                "kind": "independent_git_copy",
                "temporary": True,
                "git_metadata_shared": False,
            },
            "materialization": {
                "classification": "read_only",
                "changes": effect_changes,
                "reasons": warnings,
            },
            "input_before": {
                "contract_version": "verification-input-manifest/v1",
                "manifest_sha256": "sha256:" + "e" * 64,
                "entry_count": 500,
            },
            "input_after": {
                "contract_version": "verification-input-manifest/v1",
                "manifest_sha256": "sha256:" + "e" * 64,
                "entry_count": 500,
            },
            "effect": {
                "classification": "declared_outputs",
                "changes": effect_changes,
                "reasons": warnings,
            },
        },
        "strict_validation": {
            "ok": True,
            "errors": [],
            "warnings": warnings,
        },
        "terminal_readiness": {
            "contract_version": "terminal-readiness/v1",
            "status": "ready_with_risk",
            "terminal_allowed": True,
            "requires_human": False,
            "reasons": readiness_reasons,
            "next_commands": [
                f"pcl test read TC-{index:04d} --json" for index in range(200)
            ],
        },
        "packet": {
            "packet_id": "cp-sha256:" + "f" * 64,
            "evidence_id": "E-0002",
            "path": ".project-loop/evidence/completion-packets/packet.json",
            "outcome": "COMPLETED_WITH_RISK",
        },
        "target_transition": {
            "changed": True,
            "from_status": "in_progress",
            "to_status": "done",
        },
        "changed": True,
        "idempotent": False,
        "race_detected": False,
        "exit_code": 0,
    }

    projected = finish_output.project_finish_result_output(
        result,
        summary=True,
        output_offset=None,
        output_limit=None,
        exclude_machine_state=True,
    )

    assert projected["repository"] == result["repository"]
    assert projected["packet"] == result["packet"]
    assert projected["changes"] == []
    assert projected["harness_local_state"] == []
    assert projected["checks"][0]["evidence_id"] == "E-0001"
    assert projected["execution"]["effect"] == {
        "classification": "declared_outputs",
        "change_count": 200,
        "reason_count": 200,
    }
    assert projected["strict_validation"] == {
        "ok": True,
        "error_count": 0,
        "warning_count": 200,
    }
    assert projected["terminal_readiness"]["reason_count"] == 200
    assert projected["terminal_readiness"]["reason_counts"] == {
        "reason_0": 50,
        "reason_1": 50,
        "reason_2": 50,
        "reason_3": 50,
    }
    assert projected["output_projection"]["machine_state"]["omitted_count"] == 250
    assert len(json.dumps(projected, ensure_ascii=False).encode("utf-8")) <= 16_384


def test_finish_progress_jsonl_preserves_stdout_and_state_semantics(
    tmp_path: Path,
    capsys,
) -> None:
    quiet_root = tmp_path / "quiet"
    progress_root = tmp_path / "progress"
    _create_packet_project(quiet_root, capsys)
    _create_packet_project(progress_root, capsys)

    assert main([
        "--root", str(quiet_root), "finish", "--emit-packet",
        "--task", "T-0001", "--summary", "--json",
    ]) == 0
    quiet_capture = capsys.readouterr()
    quiet = json.loads(quiet_capture.out)["finish"]
    assert quiet_capture.err == ""
    assert "progress_delivery" not in quiet
    quiet_counts = _state_counts(quiet_root)

    assert main([
        "--root", str(progress_root), "finish", "--emit-packet",
        "--task", "T-0001", "--progress", "jsonl",
        "--summary", "--json",
    ]) == 0
    progress_capture = capsys.readouterr()
    progress_payload = json.loads(progress_capture.out)
    progress = progress_payload["finish"]
    records = [
        json.loads(line)
        for line in progress_capture.err.splitlines()
        if line.strip()
    ]

    assert progress_payload["ok"] is True
    assert _state_counts(progress_root) == quiet_counts
    assert progress["packet"]["outcome"] == quiet["packet"]["outcome"]
    assert progress["target_transition"] == quiet["target_transition"]
    assert progress["progress_delivery"] == {
        "contract_version": "finish-progress-delivery/v1",
        "format": "jsonl",
        "status": "complete",
        "emitted_count": len(records),
        "dropped_count": 0,
    }
    assert [record["sequence"] for record in records] == list(
        range(1, len(records) + 1)
    )
    assert records[0]["event"] == "finish_started"
    assert records[-1]["event"] == "finish_finished"
    assert records[-1]["status"] == "completed"
    assert any(record["event"] == "check_started" for record in records)
    assert any(record["event"] == "check_finished" for record in records)
    assert {
        record["target_binding"]["target_id"]
        for record in records
    } == {"T-0001"}
    progress_keys = _nested_keys(records)
    for forbidden in ("argv", "command", "stdout", "stderr", "environment"):
        assert forbidden not in progress_keys


def test_finish_progress_reports_incomplete_terminal_for_failed_check(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys, failing=True)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--progress", "jsonl", "--summary", "--json",
    ]) == 1
    captured = capsys.readouterr()
    finish = json.loads(captured.out)["finish"]
    records = [json.loads(line) for line in captured.err.splitlines()]

    assert finish["packet"]["outcome"] == "INCOMPLETE_VALIDATION"
    check_finished = [
        record for record in records if record["event"] == "check_finished"
    ]
    assert len(check_finished) == 1
    assert check_finished[0]["status"] == "failed"
    assert records[-1]["event"] == "finish_finished"
    assert records[-1]["status"] == "incomplete"
    assert records[-1]["outcome"] == "INCOMPLETE_VALIDATION"


def test_finish_progress_flags_fail_closed_before_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)
    before = _state_counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--dry-run",
        "--task", "T-0001", "--progress", "jsonl", "--json",
    ]) == 2
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["details"]["field"] == "progress"
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
    assert finish["execution"]["workspace"]["kind"] == "independent_git_copy"
    assert finish["execution"]["workspace"]["git_metadata_shared"] is False
    assert finish["execution"]["materialization"]["classification"] == "read_only"
    assert finish["execution"]["effect"]["classification"] == "declared_outputs"
    assert finish["checks"][0]["status"] == "passed"
    assert finish["checks"][0]["contract_version"] == "finish-check-result/v2"
    assert finish["checks"][0]["runner_result"]["status"] == "completed"
    assert finish["checks"][0]["assertion_result"]["status"] == "passed"
    assert finish["checks"][0]["failure_phase"] is None
    assert finish["checks"][0]["failure_kind"] is None
    assert finish["checks"][0]["attempt_identity"]["contract_version"] == (
        "verification-attempt-identity/v1"
    )
    assert finish["checks"][0]["stability_evaluation"]["status"] == (
        "stability_required"
    )
    assert finish["checks"][0]["stability_evaluation"]["reproducible"] is False
    assert finish["terminal_readiness"]["contract_version"] == "terminal-readiness/v1"
    assert finish["terminal_readiness"]["status"] == "ready"
    assert finish["terminal_readiness"]["reasons"][0]["code"] == (
        "finish_stability_record_only"
    )
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert validate_completion_packet(packet).ok is True
    assert packet["repository"]["diff_sha256"] == finish["repository"]["diff_sha256"]
    assert packet["checks"][0]["artifact_ref"] == f"evidence:{finish['checks'][0]['evidence_id']}"
    assert packet["checks"][0]["reproducible"] is False
    before = _state_counts(tmp_path)

    assert main(command) == 0
    rerun = _finish_payload(capsys)
    assert rerun["idempotent"] is True
    assert rerun["changed"] is False
    assert rerun["packet"] == finish["packet"]
    assert _state_counts(tmp_path) == before


def test_finish_equivalent_roles_execute_once_and_share_hash_anchored_result(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_packet_project(tmp_path, capsys)
    _configure_finish_command(
        tmp_path,
        "lint",
        "python -m pytest -q test_sample.py",
    )
    from pcl import finish_execution

    execute = finish_execution.execute_planned_guarded_command
    executed_roles: list[str] = []

    def counted_execute(paths, command, **kwargs):
        executed_roles.append(_finish_command_key(command))
        return execute(paths, command, **kwargs)

    monkeypatch.setattr(
        finish_execution,
        "execute_planned_guarded_command",
        counted_execute,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)

    assert executed_roles == ["lint"]
    assert len(finish["checks"]) == 1
    check = finish["checks"][0]
    assert check["reuse"]["contract_version"] == "check-result-reuse/v1"
    assert check["reuse"]["role_bindings"] == [
        {"check_id": "finish_checks:1", "config_key": "lint"},
        {"check_id": "finish_checks:2", "config_key": "test"},
    ]
    assert check["reuse"]["reused_role_count"] == 1
    assert check["reuse"]["compatible_history"] == []
    assert check["attempt_identity"]["execution_identity_sha256"].startswith(
        "sha256:"
    )
    assert check["artifact_sha256"].startswith("sha256:")
    assert _evidence_count(tmp_path, "completion_check") == 1

    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert len(packet["checks"]) == 1
    anchor = _latest_check_anchor(tmp_path)
    assert anchor["check_results"] == [{
        "evidence_id": check["evidence_id"],
        "sha256": check["artifact_sha256"],
    }]


def test_finish_compatible_hash_anchored_history_contributes_to_stability(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_packet_project(tmp_path, capsys)
    _configure_finish_command(
        tmp_path,
        "lint",
        "python -m pytest -q test_sample.py",
    )
    _open_task_decision(tmp_path, capsys)
    from pcl import finish_execution

    execute = finish_execution.execute_planned_guarded_command
    execution_count = 0

    def counted_execute(paths, command, **kwargs):
        nonlocal execution_count
        execution_count += 1
        return execute(paths, command, **kwargs)

    monkeypatch.setattr(
        finish_execution,
        "execute_planned_guarded_command",
        counted_execute,
    )
    command = [
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]

    assert main(command) == 0
    first = _finish_payload(capsys)
    first_check = first["checks"][0]
    assert first["packet"]["outcome"] == "INCOMPLETE_HUMAN_DECISION_REQUIRED"

    assert main(command) == 0
    second = _finish_payload(capsys)
    second_check = second["checks"][0]

    assert execution_count == 2
    assert second_check["reuse"]["compatible_history"] == [{
        "evidence_id": first_check["evidence_id"],
        "artifact_sha256": first_check["artifact_sha256"],
        "assertion_status": "passed",
        "stability_stratum": "cold",
    }]
    assert second_check["reuse"]["history_rejections"] == {}
    assert second_check["stability_evaluation"]["attempt_count"] == 2
    assert second_check["stability_evaluation"]["strata"]["cold"]["passed"] == 2
    assert second_check["stability_evaluation"]["reproducible"] is False
    assert _evidence_count(tmp_path, "completion_check") == 2


def test_finish_history_rejects_tampered_and_policy_incompatible_results(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)
    _open_task_decision(tmp_path, capsys)
    command = [
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]

    assert main(command) == 0
    first = _finish_payload(capsys)
    first_check = first["checks"][0]
    result_path = tmp_path / ".project-loop" / "evidence" / (
        f"completion-checks/{first_check['evidence_id']}/result.json"
    )
    result_path.write_text(
        result_path.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )

    assert main(command) == 0
    tamper_run = _finish_payload(capsys)
    tamper_check = tamper_run["checks"][0]
    assert tamper_check["reuse"]["compatible_history"] == []
    assert tamper_check["reuse"]["history_rejections"] == {
        "artifact_hash_mismatch": 1,
    }
    assert tamper_check["stability_evaluation"]["attempt_count"] == 1

    assert main([*command[:-1], "--timeout", "121", "--json"]) == 0
    policy_run = _finish_payload(capsys)
    assert policy_run["checks"][0]["reuse"]["history_rejections"] == {
        "artifact_hash_mismatch": 1,
        "execution_identity_mismatch": 1,
    }
    assert policy_run["checks"][0]["stability_evaluation"]["attempt_count"] == 1


def test_finish_distinct_roles_still_execute_independently(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_packet_project(tmp_path, capsys)
    _configure_finish_command(
        tmp_path,
        "lint",
        "python -m ruff check test_sample.py",
    )
    from pcl import finish_execution

    execute = finish_execution.execute_planned_guarded_command
    executed_roles: list[str] = []

    def counted_execute(paths, command, **kwargs):
        executed_roles.append(_finish_command_key(command))
        return execute(paths, command, **kwargs)

    monkeypatch.setattr(
        finish_execution,
        "execute_planned_guarded_command",
        counted_execute,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]) == 0
    finish = _finish_payload(capsys)

    assert executed_roles == ["lint", "test"]
    assert len(finish["checks"]) == 2
    assert [check["reuse"]["reused_role_count"] for check in finish["checks"]] == [0, 0]


def test_finish_input_mutation_is_isolated_and_records_attempt_without_packet(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)
    protected = tmp_path / "protected.txt"
    protected.write_text("canonical\n", encoding="utf-8")
    _git(tmp_path, "add", "protected.txt")
    _git(tmp_path, "commit", "-m", "protected fixture")
    (tmp_path / "test_sample.py").write_text(
        "from pathlib import Path\n\n"
        "def test_sample():\n"
        "    Path('protected.txt').write_text('mutated by check\\n', encoding='utf-8')\n"
        "    assert True\n",
        encoding="utf-8",
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001", "--json",
    ]) == 1
    finish = _finish_payload(capsys)

    assert protected.read_text(encoding="utf-8") == "canonical\n"
    assert finish["checks"][0]["status"] == "passed"
    assert finish["execution"]["effect"]["classification"] == "mutates_inputs"
    assert {
        "path": "protected.txt",
        "before_source": "tracked",
        "after_source": "tracked",
        "change": "modified",
    } in finish["execution"]["effect"]["changes"]
    assert finish["execution"]["effect"]["reasons"] == []
    assert finish["attempt"]["contract_version"] == "finish-attempt/v1"
    assert finish["attempt"]["outcome"] == "INCOMPLETE_VALIDATION"
    assert finish["terminal_readiness"]["status"] == "incomplete"
    assert finish["terminal_readiness"]["reasons"][0]["code"] == (
        "finish_workspace_input_mutation"
    )
    assert "packet" not in finish
    assert finish["target_transition"] == {
        "changed": False,
        "from_status": "in_progress",
        "to_status": "in_progress",
    }
    assert _evidence_count(tmp_path, "finish_attempt") == 1
    assert _evidence_count(tmp_path, "completion_packet") == 0
    attempt = json.loads(
        (tmp_path / finish["attempt"]["path"]).read_text(encoding="utf-8")
    )
    assert attempt["attempt_id"] == finish["attempt"]["attempt_id"]
    assert attempt["input_manifest"]["contract_version"] == (
        "verification-input-manifest/v1"
    )
    assert attempt["workspace"]["metadata"]["git_metadata_shared"] is False
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        event = conn.execute(
            """
            SELECT payload_json FROM events
            WHERE event_type = 'finish_attempt_recorded'
            ORDER BY sequence DESC LIMIT 1
            """
        ).fetchone()
        link = conn.execute(
            """
            SELECT link_role FROM evidence_links
            WHERE evidence_id = ?
            """,
            (finish["attempt"]["evidence_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(event["payload_json"])["attempt_id"] == attempt["attempt_id"]
    assert link["link_role"] == "finish_attempt"

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    validation = _json_output(capsys)
    assert validation["errors"] == []


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


def test_finish_blocks_linked_task_until_feature_readiness_is_complete(
    tmp_path: Path,
    capsys,
) -> None:
    _create_packet_project(tmp_path, capsys)
    assert main([
        "--root", str(tmp_path), "feature", "add", "--name", "Incomplete",
        "--surface", "cli:pcl", "--task", "T-0001",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "story", "draft", "--feature", "F-0001",
        "--actor", "operator", "--goal", "finish linked work",
        "--expected-behavior", "Human approval and passing Tests are required",
    ]) == 0
    assert main([
        "--root", str(tmp_path), "test", "plan", "--feature", "F-0001",
        "--story", "US-0001", "--type", "acceptance",
        "--scenario", "Incomplete linked work", "--expected", "not terminal",
    ]) == 0
    capsys.readouterr()

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001",
        "--json",
    ]) == 1
    finish = _finish_payload(capsys)
    assert finish["packet"]["outcome"] == "INCOMPLETE_VALIDATION"
    assert finish["terminal_readiness"]["status"] == "blocked"
    assert finish["terminal_readiness"]["reasons"][0]["code"] == (
        "feature_done_story_incomplete"
    )
    assert finish["target_transition"]["changed"] is False


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
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001",
        "--progress", "jsonl", "--json",
    ]) == 1
    captured = capsys.readouterr()
    finish = json.loads(captured.out)["finish"]
    progress = [json.loads(line) for line in captured.err.splitlines()]
    expected = "pcl finish --emit-packet --task T-0001 --timeout 600 --json"
    assert [
        record["status"]
        for record in progress
        if record["event"] == "check_finished"
    ] == ["timed_out"]
    assert progress[-1]["event"] == "finish_finished"
    assert progress[-1]["status"] == "timed_out"
    assert finish["checks"][0]["status"] == "timed_out"
    assert finish["checks"][0]["runner_result"]["status"] == "timed_out"
    assert finish["checks"][0]["assertion_result"]["status"] == "not_evaluated"
    assert finish["checks"][0]["failure_phase"] == "execute"
    assert finish["checks"][0]["failure_kind"] == "timeout"
    assert finish["checks"][0]["attempt_identity"]["contract_version"] == (
        "verification-attempt-identity/v1"
    )
    assert finish["checks"][0]["stability_evaluation"]["reproducible"] is False
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
    assert packet["checks"][0]["reproducible"] is False
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


def test_finish_timeout_at_legacy_limit_routes_to_bounded_final_retry(
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
    retry = "pcl finish --emit-packet --task T-0001 --timeout 1200 --json"
    assert finish["timeout_recovery"] == {
        "available": True,
        "reason": "finish_check_timed_out",
        "timed_out_evidence_id": evidence_id,
        "previous_timeout_seconds": 600,
        "suggested_timeout_seconds": 1200,
        "retry_command": retry,
        "diagnostic_command": f"pcl evidence show {evidence_id} --json",
    }
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["next_action"]["command"] == retry

    assert main([
        "--root", str(tmp_path), "next", "--target", "T-0001", "--json",
    ]) == 0
    action = _json_output(capsys)
    assert action["type"] == "retry_finish_timeout"
    assert action["command"] == retry
    assert action["blocking"] is False
    assert action["requires_human"] is False
    assert action["routing_scope"] == "target"
    assert action["target_binding"]["target_id"] == "T-0001"


def test_finish_timeout_at_finish_limit_routes_target_to_evidence_diagnosis(
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
        "--timeout", "1200", "--json",
    ]) == 1
    finish = _finish_payload(capsys)
    evidence_id = finish["checks"][0]["evidence_id"]
    diagnostic = f"pcl evidence show {evidence_id} --json"
    assert finish["timeout_recovery"] == {
        "available": False,
        "reason": "finish_timeout_limit_reached",
        "timed_out_evidence_id": evidence_id,
        "previous_timeout_seconds": 1200,
        "suggested_timeout_seconds": None,
        "retry_command": None,
        "diagnostic_command": diagnostic,
    }
    packet = load_completion_packet(tmp_path / finish["packet"]["path"])
    assert packet["next_action"]["command"] == diagnostic
    assert "--timeout" not in packet["next_action"]["command"]

    assert main([
        "--root", str(tmp_path), "next", "--target", "T-0001", "--json",
    ]) == 0
    action = _json_output(capsys)
    assert action["type"] == "diagnose_finish_timeout"
    assert action["command"] == diagnostic
    assert action["blocking"] is True
    assert action["requires_human"] is False
    assert action["routing_scope"] == "target"
    assert action["target_binding"]["target_id"] == "T-0001"


def test_finish_rejects_timeout_above_finish_limit_before_mutation(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    _create_packet_project(tmp_path, capsys)
    before = _state_counts(tmp_path)

    def unexpected_execution(*args, **kwargs):
        pytest.fail("finish check executed above the timeout limit")

    monkeypatch.setattr(
        "pcl.finish_execution.execute_planned_guarded_command",
        unexpected_execution,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet", "--task", "T-0001",
        "--timeout", "1201", "--json",
    ]) == 2
    error = _json_output(capsys)
    assert error == {
        "ok": False,
        "error": {
            "code": "invalid_input",
            "message": "--timeout must be 1200 seconds or less.",
            "details": {
                "timeout_seconds": 1201,
                "maximum_timeout_seconds": 1200,
            },
        },
    }
    assert _state_counts(tmp_path) == before


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

    assert main([
        "--root", str(tmp_path), "next", "--target", "T-0001", "--json",
    ]) == 0
    targeted = _json_output(capsys)
    assert targeted["type"] not in {
        "retry_finish_timeout",
        "diagnose_finish_timeout",
    }
    assert targeted["target_binding"]["target_id"] == "T-0001"


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


def test_finish_rechecks_task_hwm_before_creating_terminal_packet(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _create_packet_project(tmp_path, capsys)
    from pcl import finish_execution
    from pcl.tasks import create_task

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        before_terminal_events = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE entity_id = 'T-0001'
                  AND event_type IN (
                    'task_status_changed',
                    'completion_packet_created'
                  )
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()
    execute = finish_execution.execute_planned_guarded_command
    mutated = False

    def execute_and_mutate_state(*args, **kwargs):
        nonlocal mutated
        execute(*args, **kwargs)
        if not mutated:
            mutated = True
            create_task(
                resolve_paths(tmp_path),
                title="Concurrent HWM mutation",
            )

    monkeypatch.setattr(
        finish_execution,
        "execute_planned_guarded_command",
        execute_and_mutate_state,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]) == 1
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "finish_target_readiness_changed"
    details = payload["error"]["details"]
    assert details["mutation_committed"] is False
    expected = details["expected_terminal_readiness"]["evaluation"]
    current = details["terminal_readiness"]["evaluation"]
    assert current["evaluated_through_event_sequence"] > (
        expected["evaluated_through_event_sequence"]
    )
    assert current["input_sha256"] != expected["input_sha256"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        task = conn.execute(
            "SELECT status FROM tasks WHERE id = 'T-0001'"
        ).fetchone()
        completion_events = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE entity_id = 'T-0001'
                  AND event_type IN (
                    'task_status_changed',
                    'completion_packet_created'
                  )
                """
            ).fetchone()[0]
        )
        completion_evidence = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM evidence
                WHERE type IN ('completion_check', 'completion_packet')
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert task["status"] == "in_progress"
    assert completion_events == before_terminal_events
    assert completion_evidence == 0
    packet_dir = tmp_path / ".project-loop" / "evidence" / "completion-packets"
    assert not packet_dir.exists() or not list(packet_dir.iterdir())


def test_finish_rechecks_current_proof_input_without_hwm_change(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    proof = _prepare_finish_current_proof(tmp_path, capsys)
    copied_path = proof["copied_path"]

    from pcl import finish_execution

    execute = finish_execution.execute_planned_guarded_command
    mutated = False

    def execute_and_drift_proof(*args, **kwargs):
        nonlocal mutated
        execute(*args, **kwargs)
        if not mutated:
            mutated = True
            copied_path.write_text("drifted\n", encoding="utf-8")

    monkeypatch.setattr(
        finish_execution,
        "execute_planned_guarded_command",
        execute_and_drift_proof,
    )

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]) == 1
    details = _json_output(capsys)["error"]["details"]
    expected = details["expected_terminal_readiness"]["evaluation"]
    current = details["terminal_readiness"]["evaluation"]

    assert details["mutation_committed"] is False
    assert current["evaluated_through_event_sequence"] == (
        expected["evaluated_through_event_sequence"]
    )
    assert current["input_sha256"] != expected["input_sha256"]
    assert details["terminal_readiness"]["terminal_allowed"] is False
    assert _evidence_count(tmp_path, "completion_packet") == 0
    assert _evidence_count(tmp_path, "completion_check") == 0


def _prepare_finish_current_proof(root: Path, capsys) -> dict:
    _create_packet_project(root, capsys)
    assert main([
        "--root", str(root), "feature", "add",
        "--name", "Finish proof", "--surface", "cli:finish",
        "--task", "T-0001",
    ]) == 0
    assert main([
        "--root", str(root), "story", "draft", "--feature", "F-0001",
        "--actor", "operator", "--goal", "finish safely",
        "--expected-behavior", "proof remains healthy",
    ]) == 0
    assert main([
        "--root", str(root), "story", "approve", "US-0001",
        "--summary", "Approved",
    ]) == 0
    assert main([
        "--root", str(root), "test", "plan", "--feature", "F-0001",
        "--story", "US-0001", "--type", "acceptance",
        "--scenario", "Finish proof", "--expected", "passing",
    ]) == 0
    artifact = root / "finish-proof.txt"
    artifact.write_text("passed\n", encoding="utf-8")
    capsys.readouterr()
    assert main([
        "--root", str(root), "evidence", "add",
        "--file", artifact.name, "--summary", "Finish acceptance",
        "--copy", "--json",
    ]) == 0
    evidence = _json_output(capsys)["evidence"]
    assert main([
        "--root", str(root), "test", "pass", "TC-0001",
        "--summary", "Passed", "--evidence-id", evidence["id"],
    ]) == 0
    assert main([
        "--root", str(root), "feature", "status", "F-0001",
        "--status", "done", "--summary", "Feature accepted",
        "--evidence-id", evidence["id"],
    ]) == 0
    capsys.readouterr()
    manifest_path = root / str(evidence["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    copied_path = root / str(manifest["members"][0]["stored_path"])
    return {
        "copied_path": copied_path,
        "evidence": evidence,
        "manifest": manifest,
        "manifest_path": manifest_path,
    }


def test_finish_rejects_coherent_proof_substitution_before_terminal_artifacts(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    proof = _prepare_finish_current_proof(tmp_path, capsys)
    copied_path = proof["copied_path"]
    manifest_path = proof["manifest_path"]

    from pcl import finish_execution

    execute = finish_execution.execute_planned_guarded_command
    mutated = False

    def execute_and_substitute_proof(*args, **kwargs):
        nonlocal mutated
        execute(*args, **kwargs)
        if not mutated:
            mutated = True
            replacement = b"coherently substituted during checks\n"
            copied_path.write_bytes(replacement)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["members"][0]["size_bytes"] = len(replacement)
            manifest["members"][0]["sha256"] = hashlib.sha256(
                replacement
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        finish_execution,
        "execute_planned_guarded_command",
        execute_and_substitute_proof,
    )
    before = _terminal_artifact_snapshot(tmp_path)

    assert main([
        "--root", str(tmp_path), "finish", "--emit-packet",
        "--task", "T-0001", "--json",
    ]) == 1
    details = _json_output(capsys)["error"]["details"]
    expected = details["expected_terminal_readiness"]["evaluation"]
    current = details["terminal_readiness"]["evaluation"]

    assert details["mutation_committed"] is False
    assert current["evaluated_through_event_sequence"] == (
        expected["evaluated_through_event_sequence"]
    )
    assert current["input_sha256"] != expected["input_sha256"]
    assert details["terminal_readiness"]["terminal_allowed"] is False
    assert "strict_manifest_event_mismatch" in {
        reason["code"]
        for reason in details["terminal_readiness"]["reasons"]
    }
    assert _terminal_artifact_snapshot(tmp_path) == before


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
    assert finish["terminal_readiness"]["status"] == "blocked"
    assert finish["terminal_readiness"]["reasons"][0]["code"] == (
        "finish_human_decision_required"
    )
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
    assert finish["terminal_readiness"]["status"] == "blocked"
    assert finish["terminal_readiness"]["reasons"][0]["code"] == (
        "finish_budget_exhausted"
    )
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
