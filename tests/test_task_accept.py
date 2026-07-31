from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect

from task_accept_helpers import accept_args, prepare_acceptance, run_json, state_counts


ENVELOPE_KEYS = {
    "authority",
    "business_attempt_generation",
    "business_changed",
    "changed",
    "effects",
    "error_code",
    "exit_code",
    "identity",
    "message",
    "mode",
    "mutation_committed",
    "ok",
    "operation",
    "pending_tail",
    "phase",
    "prior_acceptance_verified",
    "prior_authoritative_commit",
    "receipts",
    "safe_retry_action",
    "safe_to_retry_original",
    "schema_version",
    "status",
    "tail_recovery_changed",
    "tail_recovery_generation",
    "teardown",
    "validation",
}


def test_atomic_accept_closes_tests_feature_and_task_with_one_base_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    before = state_counts(tmp_path)

    result = run_json(tmp_path, capsys, *accept_args(fixture))

    assert set(result) == ENVELOPE_KEYS
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["mutation_committed"] is True
    assert result["business_changed"] is True
    assert result["prior_acceptance_verified"] is False
    assert result["schema_version"] == "task-accept-envelope/v1"
    assert result["effects"]["events_appended"] == 6
    assert result["effects"]["outbox_records_appended"] == 6
    assert result["effects"]["copies_published"] == 1
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        authority_payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM events WHERE id = ?",
                (result["authority"]["event_id"],),
            ).fetchone()["payload_json"]
        )
    finally:
        conn.close()
    proof = authority_payload["task_acceptance"]["current_proof_identity"]
    assert set(proof) == {
        "acceptance_hwm",
        "contract_version",
        "digest",
        "evidence_links_sha256",
        "evidence_row_sha256",
        "input_digest",
        "manifest_sha256",
        "member_record_sha256",
        "member_sha256",
        "recording_event_id",
        "recording_event_sha256",
        "recording_event_suffix_sha256",
    }
    assert proof["input_digest"] == result["identity"]["request_id"]
    assert proof["acceptance_hwm"]["event_id"] == result["authority"]["event_id"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        task = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (fixture["task_id"],)
        ).fetchone()
        feature = conn.execute(
            "SELECT status FROM features WHERE id = ?", (fixture["feature_id"],)
        ).fetchone()
        tests = conn.execute(
            "SELECT id, status, evidence_id FROM test_cases WHERE feature_id = ? ORDER BY id",
            (fixture["feature_id"],),
        ).fetchall()
        evidence = conn.execute(
            "SELECT id, type, path, command, summary FROM evidence ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        links = conn.execute(
            "SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ? ORDER BY target_type, target_id",
            (evidence["id"],),
        ).fetchall()
        suffix = conn.execute(
            "SELECT event_type, entity_id FROM events WHERE sequence > ? ORDER BY sequence",
            (before["events"],),
        ).fetchall()
    finally:
        conn.close()

    assert task["status"] == "done"
    assert feature["status"] == "done"
    assert [(row["id"], row["status"], row["evidence_id"]) for row in tests] == [
        (test_id, "passing", evidence["id"]) for test_id in fixture["test_ids"]
    ]
    assert evidence["type"] == "adhoc_artifact"
    assert evidence["command"] == "pytest -q"
    assert evidence["summary"] == "Acceptance verified"
    assert [(row["target_type"], row["target_id"], row["link_role"]) for row in links] == [
        ("feature", fixture["feature_id"], "acceptance"),
        ("task", fixture["task_id"], "supporting"),
        *[("test_case", test_id, "acceptance") for test_id in fixture["test_ids"]],
    ]
    assert [(row["event_type"], row["entity_id"]) for row in suffix] == [
        ("adhoc_evidence_recorded", evidence["id"]),
        ("test_case_passed", fixture["test_ids"][0]),
        ("feature_status_updated", fixture["feature_id"]),
        ("test_case_passed", fixture["test_ids"][1]),
        ("feature_status_updated", fixture["feature_id"]),
        ("task_status_changed", fixture["task_id"]),
    ]


def test_exact_retry_has_zero_business_projection_render_and_marker_effects(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    first = run_json(tmp_path, capsys, *accept_args(fixture))
    before = state_counts(tmp_path)
    dashboard_before = {
        name: (tmp_path / ".project-loop" / "dashboard" / name).read_bytes()
        for name in ("dashboard.html", "dashboard-data.json")
    }

    replay = run_json(tmp_path, capsys, *accept_args(fixture))

    assert replay["ok"] is True
    assert replay["status"] == "no_op"
    assert replay["business_changed"] is False
    assert replay["changed"] is False
    assert replay["mutation_committed"] is False
    assert replay["prior_acceptance_verified"] is True
    assert replay["identity"] == first["identity"]
    assert len(replay["effects"]) == 25
    assert set(replay["effects"].values()) == {0}
    assert state_counts(tmp_path) == before
    assert {
        name: (tmp_path / ".project-loop" / "dashboard" / name).read_bytes()
        for name in dashboard_before
    } == dashboard_before


def test_different_request_for_accepted_task_is_conflict_and_zero_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    run_json(tmp_path, capsys, *accept_args(fixture))
    before = state_counts(tmp_path)

    conflict = run_json(
        tmp_path,
        capsys,
        *accept_args(fixture, summary="A different request"),
        expected_exit=1,
    )

    assert conflict["error_code"] == "task_accept_task_request_conflict"
    assert conflict["mutation_committed"] is False
    assert conflict["safe_to_retry_original"] is False
    assert state_counts(tmp_path) == before


def test_story_guard_rolls_back_all_database_state(tmp_path: Path, capsys) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, approve_story=False)
    before = state_counts(tmp_path)

    rejected = run_json(
        tmp_path,
        capsys,
        *accept_args(fixture),
        expected_exit=1,
    )

    assert rejected["error_code"] == "task_accept_story_not_terminal"
    assert rejected["mutation_committed"] is False
    assert rejected["effects"]["db_mutations_total"] == 0
    assert state_counts(tmp_path) == before


def test_cli_text_success_and_json_are_two_views_of_same_result(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)

    assert main(["--root", str(tmp_path), *accept_args(fixture)]) == 0
    captured = capsys.readouterr()

    assert captured.err == ""
    assert captured.out.startswith(
        f"OK task_accept fresh_success: Task {fixture['task_id']} accepted atomically "
    )
    assert not captured.out.lstrip().startswith("{")


def test_copy_and_at_least_one_test_are_fixed_cli_requirements(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)
    base = [
        "--root",
        str(tmp_path),
        "task",
        "accept",
        fixture["task_id"],
        "--artifact",
        fixture["artifact"],
        "--command",
        "pytest -q",
        "--summary",
        "verified",
        "--json",
    ]

    assert main(base + ["--test", fixture["test_ids"][0]]) == 2
    copy_error = json.loads(capsys.readouterr().out)
    assert copy_error["error_code"] == "task_accept_copy_required"
    assert main(base + ["--copy"]) == 2
    test_error = json.loads(capsys.readouterr().out)
    assert test_error["error_code"] == "task_accept_usage_error"


def test_not_initialized_uses_exit3_json_contract(tmp_path: Path, capsys) -> None:
    args = [
        "--root",
        str(tmp_path),
        "task",
        "accept",
        "T-0001",
        "--artifact",
        "artifact.txt",
        "--command",
        "pytest -q",
        "--summary",
        "verified",
        "--copy",
        "--test",
        "TC-0001",
        "--json",
    ]

    assert main(args) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["error_code"] == "task_accept_not_initialized"
    # M5 distinguishes correcting input/environment for a new invocation from
    # automatically retrying the original argv.
    assert result["safe_to_retry_original"] is False


def test_one_invalid_test_in_multi_test_request_rolls_back_entire_bundle(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=1)
    story = run_json(
        tmp_path,
        capsys,
        "story",
        "draft",
        "--feature",
        fixture["feature_id"],
        "--actor",
        "operator",
        "--goal",
        "cover a second semantic case",
        "--expected-behavior",
        "must remain blocked before approval",
    )
    planned = run_json(
        tmp_path,
        capsys,
        "test",
        "plan",
        "--feature",
        fixture["feature_id"],
        "--story",
        story["id"],
        "--type",
        "integration",
        "--scenario",
        "second acceptance check",
        "--expected",
        "passing",
    )
    fixture["test_ids"].append(planned["id"])
    before = state_counts(tmp_path)

    rejected = run_json(
        tmp_path,
        capsys,
        *accept_args(fixture),
        expected_exit=1,
    )

    assert rejected["error_code"] == "task_accept_story_not_terminal"
    assert state_counts(tmp_path) == before
