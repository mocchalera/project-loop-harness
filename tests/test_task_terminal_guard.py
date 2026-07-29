from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from pcl.cli import main
from pcl.db import connect
from pcl.errors import TaskTerminalReadinessError
from pcl.paths import resolve_paths
from pcl.tasks import add_dependency, set_task_status


def _json_output(capsys) -> dict[str, Any]:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _run_json(root: Path, capsys, *args: str) -> dict[str, Any]:
    assert main(["--root", str(root), *args, "--json"]) == 0
    return _json_output(capsys)


def _prepare_linked_task(
    root: Path,
    capsys,
    *,
    feature_done: bool,
) -> dict[str, str]:
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json_output(capsys)
    _run_json(root, capsys, "start", "P0-B terminal guard fixture")
    _run_json(
        root,
        capsys,
        "feature",
        "add",
        "--name",
        "Terminal guard",
        "--surface",
        "cli:task-status",
        "--task",
        "T-0001",
    )
    _run_json(
        root,
        capsys,
        "story",
        "draft",
        "--feature",
        "F-0001",
        "--actor",
        "operator",
        "--goal",
        "close only a ready Task",
        "--expected-behavior",
        "unsafe done is rejected without mutation",
    )
    _run_json(
        root,
        capsys,
        "story",
        "approve",
        "US-0001",
        "--summary",
        "Approved fixture semantics",
    )
    _run_json(
        root,
        capsys,
        "test",
        "plan",
        "--feature",
        "F-0001",
        "--story",
        "US-0001",
        "--type",
        "acceptance",
        "--scenario",
        "Terminal guard fixture passes",
        "--expected",
        "Task readiness is deterministic",
    )
    artifact = root / "terminal-guard-acceptance.txt"
    artifact.write_text("passed\n", encoding="utf-8")
    evidence = _run_json(
        root,
        capsys,
        "evidence",
        "add",
        "--file",
        artifact.name,
        "--summary",
        "Terminal guard acceptance",
        "--copy",
    )
    evidence_id = str(evidence["evidence"]["id"])
    _run_json(
        root,
        capsys,
        "test",
        "pass",
        "TC-0001",
        "--summary",
        "Acceptance passed",
        "--evidence-id",
        evidence_id,
    )
    if feature_done:
        _run_json(
            root,
            capsys,
            "feature",
            "status",
            "F-0001",
            "--status",
            "done",
            "--summary",
            "Feature acceptance is complete",
            "--evidence-id",
            evidence_id,
        )
    return {
        "goal_id": "G-0001",
        "task_id": "T-0001",
        "feature_id": "F-0001",
        "test_id": "TC-0001",
        "evidence_id": evidence_id,
    }


def _mutation_snapshot(root: Path, task_id: str) -> dict[str, Any]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        task = dict(
            conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        )
        events = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, sequence, event_type, entity_type, entity_id, payload_json, created_at
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
                       next_attempt_at, last_error, created_at, updated_at, delivered_at
                FROM outbox_records
                ORDER BY id
                """
            ).fetchall()
        ]
    finally:
        conn.close()
    dashboard_dir = root / ".project-loop" / "dashboard"
    return {
        "task": task,
        "events": events,
        "outbox": outbox,
        "events_jsonl": (root / ".project-loop" / "events.jsonl").read_bytes(),
        "dashboard_html": (dashboard_dir / "dashboard.html").read_bytes(),
        "dashboard_data": (dashboard_dir / "dashboard-data.json").read_bytes(),
    }


def test_direct_done_requires_linked_feature_done_and_is_zero_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=False)
    before = _mutation_snapshot(tmp_path, fixture["task_id"])

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Unsafe direct close",
            "--json",
        ]
    ) == 1
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "task_terminal_readiness_failed"
    assert payload["error"]["details"]["mutation_committed"] is False
    readiness = payload["error"]["details"]["terminal_readiness"]
    assert readiness["terminal_allowed"] is False
    assert [reason["code"] for reason in readiness["reasons"]] == [
        "task_done_feature_not_terminal"
    ]
    assert _mutation_snapshot(tmp_path, fixture["task_id"]) == before


def test_direct_done_rejects_incomplete_dependency_without_tail_or_artifact_change(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    first = _run_json(
        tmp_path,
        capsys,
        "task",
        "create",
        "--title",
        "Dependent",
    )
    dependency = _run_json(
        tmp_path,
        capsys,
        "task",
        "create",
        "--title",
        "Foundation",
    )
    _run_json(
        tmp_path,
        capsys,
        "task",
        "depend",
        str(first["id"]),
        "--on",
        str(dependency["id"]),
    )
    _run_json(tmp_path, capsys, "render")
    before = _mutation_snapshot(tmp_path, str(first["id"]))

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            str(first["id"]),
            "done",
            "--reason",
            "Dependency is not done",
            "--json",
        ]
    ) == 1
    payload = _json_output(capsys)

    assert payload["error"]["code"] == "task_terminal_readiness_failed"
    readiness = payload["error"]["details"]["terminal_readiness"]
    assert readiness["reasons"][0]["code"] == "task_done_dependency_incomplete"
    assert "mutation_tail" not in payload
    assert _mutation_snapshot(tmp_path, str(first["id"])) == before


def test_already_done_skips_terminal_preflight_even_if_current_readiness_blocks(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    task = _run_json(
        tmp_path,
        capsys,
        "task",
        "create",
        "--title",
        "Already terminal",
    )
    dependency = _run_json(
        tmp_path,
        capsys,
        "task",
        "create",
        "--title",
        "Late dependency",
    )
    _run_json(
        tmp_path,
        capsys,
        "task",
        "status",
        str(task["id"]),
        "done",
        "--reason",
        "Standalone completion",
    )
    _run_json(
        tmp_path,
        capsys,
        "task",
        "depend",
        str(task["id"]),
        "--on",
        str(dependency["id"]),
    )
    before = _mutation_snapshot(tmp_path, str(task["id"]))

    repeated = _run_json(
        tmp_path,
        capsys,
        "task",
        "status",
        str(task["id"]),
        "done",
        "--reason",
        "Exact retry",
    )

    assert repeated["changed"] is False
    assert repeated["mutation_tail"]["mutation_committed"] is False
    assert repeated["mutation_tail"]["render"]["status"] == "not_changed"
    assert "terminal_readiness" not in repeated
    assert _mutation_snapshot(tmp_path, str(task["id"])) == before


def test_two_concurrent_done_requests_commit_one_event_and_one_receipt(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    paths = resolve_paths(tmp_path)

    def close_task(reason: str) -> dict[str, Any]:
        return set_task_status(
            paths,
            fixture["task_id"],
            status="done",
            reason=reason,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(close_task, ("first", "second")))

    assert sorted(result["changed"] for result in results) == [False, True]
    changed = next(result for result in results if result["changed"])
    assert changed["terminal_readiness"]["terminal_allowed"] is True
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        events = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type = 'task_status_changed' AND entity_id = ?
            ORDER BY sequence
            """,
            (fixture["task_id"],),
        ).fetchall()
    finally:
        conn.close()
    assert len(events) == 1
    event_payload = json.loads(str(events[0]["payload_json"]))
    assert event_payload["terminal_readiness"] == changed["terminal_readiness"]


def test_dependency_commit_wins_race_and_done_rechecks_inside_its_transaction(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert main(["init", "--target", str(tmp_path), "--json"]) == 0
    _json_output(capsys)
    task = _run_json(
        tmp_path, capsys, "task", "create", "--title", "Race target"
    )
    dependency = _run_json(
        tmp_path, capsys, "task", "create", "--title", "Race dependency"
    )
    paths = resolve_paths(tmp_path)
    dependency_event_appended = Event()
    allow_dependency_commit = Event()

    import pcl.tasks as tasks_module

    original_append_event = tasks_module.append_event

    def append_event_with_pause(*args, **kwargs):
        event_id = original_append_event(*args, **kwargs)
        if kwargs.get("event_type") == "task_dependency_added":
            dependency_event_appended.set()
            assert allow_dependency_commit.wait(timeout=5)
        return event_id

    monkeypatch.setattr(tasks_module, "append_event", append_event_with_pause)

    with ThreadPoolExecutor(max_workers=2) as executor:
        dependency_future = executor.submit(
            add_dependency,
            paths,
            str(task["id"]),
            depends_on_task_id=str(dependency["id"]),
        )
        assert dependency_event_appended.wait(timeout=5)
        done_future = executor.submit(
            set_task_status,
            paths,
            str(task["id"]),
            status="done",
            reason="Concurrent close",
        )
        allow_dependency_commit.set()
        assert dependency_future.result(timeout=5)["depends_on_task_id"] == dependency["id"]
        with pytest.raises(TaskTerminalReadinessError) as exc_info:
            done_future.result(timeout=5)

    readiness = exc_info.value.details["terminal_readiness"]
    assert readiness["reasons"][0]["code"] == "task_done_dependency_incomplete"
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT status FROM tasks WHERE id = ?",
            (task["id"],),
        ).fetchone()
        status_events = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE event_type = 'task_status_changed' AND entity_id = ?
                """,
                (task["id"],),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert row["status"] == "todo"
    assert status_events == 0


def test_terminal_readiness_failure_text_is_stderr_only_and_ordered(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=False)

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Unsafe direct close",
        ]
    ) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err.splitlines() == [
        "ERROR: Task T-0001 is not ready for done.",
        "BLOCKED task_done_feature_not_terminal: Feature F-0001 is passing, not done.",
        "NEXT: pcl feature read F-0001 --json",
    ]


def test_read_list_next_and_direct_done_share_one_snapshot_digest(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)

    read = _run_json(
        tmp_path, capsys, "task", "read", fixture["task_id"]
    )["task"]
    listed = _run_json(tmp_path, capsys, "task", "list")["tasks"][0]
    next_action = _run_json(
        tmp_path, capsys, "next", "--target", fixture["task_id"]
    )
    closed = _run_json(
        tmp_path,
        capsys,
        "task",
        "status",
        fixture["task_id"],
        "done",
        "--reason",
        "Shared snapshot is ready",
    )

    receipts = [
        read["terminal_readiness"],
        listed["terminal_readiness"],
        next_action["target"]["terminal_readiness"],
        closed["terminal_readiness"],
    ]
    assert {receipt["status"] for receipt in receipts} == {"ready"}
    assert {
        receipt["evaluation"]["input_sha256"] for receipt in receipts
    } == {receipts[0]["evaluation"]["input_sha256"]}
    assert {
        receipt["evaluation"]["evaluated_through_event_sequence"]
        for receipt in receipts
    } == {receipts[0]["evaluation"]["evaluated_through_event_sequence"]}
    assert [receipt["evaluation"]["source"] for receipt in receipts] == [
        "task_read",
        "task_read",
        "next",
        "task_status",
    ]
    assert closed["mutation_tail"]["mutation_committed"] is True

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        event = conn.execute(
            """
            SELECT payload_json
            FROM events
            WHERE event_type = 'task_status_changed' AND entity_id = ?
            """,
            (fixture["task_id"],),
        ).fetchone()
        outbox_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM outbox_records
                JOIN events ON events.id = outbox_records.event_id
                WHERE events.event_type = 'task_status_changed'
                  AND events.entity_id = ?
                """,
                (fixture["task_id"],),
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert event is not None
    assert json.loads(str(event["payload_json"]))["terminal_readiness"] == closed[
        "terminal_readiness"
    ]
    assert outbox_count == 1


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            "UPDATE user_stories SET status = 'draft' WHERE id = 'US-0001'",
            "feature_done_story_incomplete",
        ),
        (
            "UPDATE test_cases SET status = 'planned' WHERE id = 'TC-0001'",
            "feature_done_tests_incomplete",
        ),
        (
            """
            INSERT INTO defects(
              id, feature_id, test_case_id, severity, expected, actual,
              reproduction, status, evidence_id, created_at, updated_at
            ) VALUES (
              'D-9999', 'F-0001', 'TC-0001', 'high', 'ready', 'broken',
              'fixture', 'open', NULL,
              '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """,
            "feature_done_open_defects",
        ),
        (
            "UPDATE goals SET status = 'closed' WHERE id = 'G-0001'",
            "task_terminal_goal_contradiction",
        ),
    ],
)
def test_current_feature_story_test_defect_and_goal_contradictions_block(
    tmp_path: Path,
    capsys,
    mutation: str,
    expected_code: str,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(mutation)
        conn.commit()
    finally:
        conn.close()
    before = _mutation_snapshot(tmp_path, fixture["task_id"])

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Must fail closed",
            "--json",
        ]
    ) == 1
    payload = _json_output(capsys)

    assert expected_code in {
        reason["code"]
        for reason in payload["error"]["details"]["terminal_readiness"]["reasons"]
    }
    assert _mutation_snapshot(tmp_path, fixture["task_id"]) == before


@pytest.mark.parametrize(
    ("mutation", "detail_reason"),
    [
        (
            """
            DELETE FROM evidence_links
            WHERE target_type = 'feature' AND target_id = 'F-0001'
              AND link_role = 'acceptance'
            """,
            "missing_target_bound_evidence",
        ),
        (
            "UPDATE evidence SET type = 'feature_status' WHERE id = 'E-0001'",
            "wrong_evidence_type",
        ),
        (
            """
            UPDATE evidence_links
            SET target_id = 'F-9999'
            WHERE target_type = 'feature' AND target_id = 'F-0001'
              AND link_role = 'acceptance'
            """,
            "missing_target_bound_evidence",
        ),
    ],
)
def test_feature_acceptance_evidence_type_and_target_binding_fail_closed(
    tmp_path: Path,
    capsys,
    mutation: str,
    detail_reason: str,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    mutation = mutation.replace("E-0001", fixture["evidence_id"])
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(mutation)
        conn.commit()
    finally:
        conn.close()

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Evidence must be healthy",
            "--json",
        ]
    ) == 1
    readiness = _json_output(capsys)["error"]["details"]["terminal_readiness"]
    evidence_reasons = [
        reason
        for reason in readiness["reasons"]
        if reason["code"] == "feature_done_evidence_required"
    ]

    assert evidence_reasons
    assert any(
        reason["details"].get("reason") == detail_reason
        for reason in evidence_reasons
    )


def test_drifted_and_superseded_current_evidence_block_but_unrelated_history_is_advisory(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    current_id = fixture["evidence_id"]
    historical_artifact = tmp_path / "historical.txt"
    historical_artifact.write_text("old\n", encoding="utf-8")
    historical = _run_json(
        tmp_path,
        capsys,
        "evidence",
        "add",
        "--file",
        historical_artifact.name,
        "--summary",
        "Unrelated history",
        "--copy",
    )
    replacement_artifact = tmp_path / "replacement.txt"
    replacement_artifact.write_text("new\n", encoding="utf-8")
    replacement = _run_json(
        tmp_path,
        capsys,
        "evidence",
        "add",
        "--file",
        replacement_artifact.name,
        "--summary",
        "Replacement",
        "--copy",
    )
    _run_json(
        tmp_path,
        capsys,
        "evidence",
        "supersede",
        str(historical["evidence"]["id"]),
        "--with",
        str(replacement["evidence"]["id"]),
        "--summary",
        "Historical proof replaced",
    )
    historical_manifest = tmp_path / str(historical["evidence"]["manifest_path"])
    historical_manifest.write_text("{}\n", encoding="utf-8")

    read = _run_json(
        tmp_path, capsys, "task", "read", fixture["task_id"]
    )["task"]["terminal_readiness"]
    assert any(
        reason["state"] == "advisory"
        and reason["details"].get("proof_scope") == "historical"
        for reason in read["reasons"]
    )
    assert read["terminal_allowed"] is True

    _run_json(
        tmp_path,
        capsys,
        "evidence",
        "supersede",
        current_id,
        "--with",
        str(replacement["evidence"]["id"]),
        "--summary",
        "Current proof was replaced",
    )
    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Current proof must be rechecked",
            "--json",
        ]
    ) == 1
    blocked = _json_output(capsys)["error"]["details"]["terminal_readiness"]
    assert blocked["terminal_allowed"] is False
    assert any(
        reason["code"] == "feature_done_evidence_required"
        and reason["details"].get("reason") == "evidence_superseded"
        for reason in blocked["reasons"]
    )


def test_copied_evidence_hash_drift_blocks_current_proof(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT path FROM evidence WHERE id = ?",
            (fixture["evidence_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    manifest = json.loads((tmp_path / str(row["path"])).read_text(encoding="utf-8"))
    copied_path = tmp_path / str(manifest["members"][0]["stored_path"])
    copied_path.write_text("drifted\n", encoding="utf-8")

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Drift must block",
            "--json",
        ]
    ) == 1
    reasons = _json_output(capsys)["error"]["details"]["terminal_readiness"][
        "reasons"
    ]
    assert any(
        reason["code"] == "feature_done_evidence_required"
        and reason["details"].get("reason") == "artifact_unhealthy"
        for reason in reasons
    )


@pytest.mark.parametrize(
    ("run_status", "run_goal_id", "job_status", "verification_result", "expected_code"),
    [
        (
            "passed",
            "G-0002",
            "passed",
            "approved",
            "task_terminal_workflow_goal_mismatch",
        ),
        (
            "running",
            "G-0001",
            "passed",
            "approved",
            "task_terminal_workflow_run_incomplete",
        ),
        (
            "passed",
            "G-0001",
            "queued",
            "approved",
            "workflow_run_passed_jobs_incomplete",
        ),
        (
            "passed",
            "G-0001",
            "passed",
            None,
            "workflow_run_passed_verification_missing",
        ),
    ],
)
def test_workflow_goal_run_jobs_and_verification_are_terminal_requirements(
    tmp_path: Path,
    capsys,
    run_status: str,
    run_goal_id: str,
    job_status: str,
    verification_result: str | None,
    expected_code: str,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    _run_json(tmp_path, capsys, "goal", "create", "--title", "Other Goal")
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO workflows(id, name, type, template_path, version, created_at)
            VALUES ('W-9999', 'Guard fixture', 'test', NULL, '1', ?)
            """,
            ("2026-01-01T00:00:00Z",),
        )
        conn.execute(
            """
            INSERT INTO workflow_runs(
              id, goal_id, workflow_id, status, iteration, started_at, ended_at, summary
            ) VALUES ('WR-9999', ?, 'W-9999', ?, 1, ?, NULL, 'fixture')
            """,
            (run_goal_id, run_status, "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO agent_jobs(
              id, workflow_run_id, role, status, started_at, summary
            ) VALUES ('J-9999', 'WR-9999', 'tester', ?, ?, 'fixture')
            """,
            (job_status, "2026-01-01T00:00:00Z"),
        )
        if verification_result is not None:
            conn.execute(
                """
                INSERT INTO verifications(
                  id, workflow_run_id, target_job_id, verifier_role, rubric_json,
                  result, reasons_json, created_at
                ) VALUES (
                  'V-9999', 'WR-9999', 'J-9999', 'reviewer', '{}',
                  ?, '[]', ?
                )
                """,
                (verification_result, "2026-01-01T00:00:00Z"),
            )
        conn.execute(
            "UPDATE test_cases SET last_run_id = 'WR-9999' WHERE id = 'TC-0001'"
        )
        conn.commit()
    finally:
        conn.close()

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Workflow proof must be complete",
            "--json",
        ]
    ) == 1
    reasons = _json_output(capsys)["error"]["details"]["terminal_readiness"][
        "reasons"
    ]
    assert expected_code in {reason["code"] for reason in reasons}


@pytest.mark.parametrize(
    ("goal_mutation", "expected_code"),
    [
        (
            "UPDATE goals SET budget_json = '{\"exhausted\": true}' WHERE id = 'G-0001'",
            "task_terminal_goal_budget_exhausted",
        ),
        (
            """
            INSERT INTO decisions(
              id, status, question, recommendation, selected_option, reason,
              blocks_json, created_at, resolved_at
            ) VALUES (
              'DEC-9999', 'open', 'Proceed?', NULL, NULL, NULL,
              '[{"type":"task","id":"T-0001"}]',
              '2026-01-01T00:00:00Z', NULL
            )
            """,
            "task_terminal_decision_open",
        ),
    ],
)
def test_goal_budget_and_human_decision_block_direct_done(
    tmp_path: Path,
    capsys,
    goal_mutation: str,
    expected_code: str,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(goal_mutation)
        conn.commit()
    finally:
        conn.close()

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Goal guards apply",
            "--json",
        ]
    ) == 1
    readiness = _json_output(capsys)["error"]["details"]["terminal_readiness"]
    assert expected_code in {reason["code"] for reason in readiness["reasons"]}


@pytest.mark.parametrize("incomplete", [False, True])
def test_evidence_set_completeness_and_policy_receipt_are_required(
    tmp_path: Path,
    capsys,
    incomplete: bool,
) -> None:
    fixture = _prepare_linked_task(tmp_path, capsys, feature_done=True)
    artifact = json.loads(
        (
            Path(__file__).parent / "fixtures" / "evidence_set" / "minimal.json"
        ).read_text(encoding="utf-8")
    )
    artifact["target"] = {"type": "test_case", "id": "TC-0001"}
    if incomplete:
        artifact["included_reports"][0]["status"] = "fail"
        artifact["completeness"] = {
            "status": "incomplete",
            "findings": [
                {
                    "code": "required_report_not_passing",
                    "kind": "visual_check",
                    "path": "reports/visual-check.json",
                    "severity": "error",
                }
            ],
        }
    evidence_set_path = tmp_path / "evidence-set.json"
    evidence_set_path.write_text(
        json.dumps(artifact, sort_keys=True),
        encoding="utf-8",
    )
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            """
            INSERT INTO evidence(id, type, path, command, summary, created_at)
            VALUES (
              'E-9999', 'evidence_set', 'evidence-set.json', NULL,
              'Evidence Set fixture', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO evidence_links(
              evidence_id, target_type, target_id, link_role, created_at
            ) VALUES (
              'E-9999', 'test_case', 'TC-0001', 'acceptance',
              '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            "UPDATE test_cases SET evidence_id = 'E-9999' WHERE id = 'TC-0001'"
        )
        conn.commit()
    finally:
        conn.close()

    assert main(
        [
            "--root",
            str(tmp_path),
            "task",
            "status",
            fixture["task_id"],
            "done",
            "--reason",
            "Evidence Set must be terminal",
            "--json",
        ]
    ) == 1
    readiness = _json_output(capsys)["error"]["details"]["terminal_readiness"]
    assert any(
        reason["code"] == "test_acceptance_evidence_required"
        and reason["state"] == "blocked"
        for reason in readiness["reasons"]
    )
