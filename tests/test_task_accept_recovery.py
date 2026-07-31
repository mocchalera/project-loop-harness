from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from pcl.cli import main
from pcl.db import MutationConnection, connect
from pcl.outbox import ProjectionResult
from pcl.paths import resolve_paths
from pcl.task_accept import accept_task

from task_accept_helpers import accept_args, json_output, prepare_acceptance, run_json, state_counts


def _accepted_evidence_id(root: Path, authority_event_id: str) -> str:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM events WHERE id = ?", (authority_event_id,)
            ).fetchone()["payload_json"]
        )
    finally:
        conn.close()
    return str(payload["task_acceptance"]["base_evidence_id"])


def _service(root: Path, fixture: dict, *, summary: str = "Acceptance verified") -> dict:
    return accept_task(
        resolve_paths(root),
        task_id=fixture["task_id"],
        artifact_path=fixture["artifact"],
        command="pytest -q",
        summary=summary,
        copy_files=True,
        test_ids=fixture["test_ids"],
    )


def _crash_command(root: Path, fixture: dict, point: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PCL_ENABLE_TEST_FAULTS": "1",
        "PCL_TEST_FAULT_POINT": point,
    }
    return subprocess.run(
        [sys.executable, "-m", "pcl", "--root", str(root), *accept_args(fixture), "--json"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_same_request_concurrency_has_one_fresh_and_one_exact_replay(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _service(tmp_path, fixture), range(2)))

    assert sorted(result["status"] for result in results) == [
        "no_op",
        "success",
    ]
    assert sum(int(result["business_changed"]) for result in results) == 1


def test_different_request_concurrency_has_one_fresh_and_one_conflict(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_service, tmp_path, fixture, summary=summary)
            for summary in ("Acceptance A", "Acceptance B")
        ]
        results = [future.result() for future in futures]

    assert sorted(result["status"] for result in results) == ["error", "success"]
    conflict = next(result for result in results if not result["ok"])
    assert conflict["error_code"] == "task_accept_task_request_conflict"
    assert conflict["mutation_committed"] is False
    assert sum(int(result["business_changed"]) for result in results) == 1


def test_tampered_current_member_blocks_exact_replay(tmp_path: Path, capsys) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    accepted = _service(tmp_path, fixture)
    evidence_id = _accepted_evidence_id(tmp_path, accepted["authority"]["event_id"])
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT path FROM evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
    finally:
        conn.close()
    manifest = json.loads((tmp_path / row["path"]).read_text(encoding="utf-8"))
    copied = tmp_path / manifest["members"][0]["stored_path"]
    copied.write_bytes(b"tampered\n")
    before = state_counts(tmp_path)

    replay = _service(tmp_path, fixture)

    assert replay["ok"] is False
    assert replay["error_code"] == "task_accept_replay_not_current"
    # M5 only permits this flag after live current-proof validation succeeds.
    assert replay["prior_acceptance_verified"] is False
    assert replay["mutation_committed"] is False
    assert state_counts(tmp_path) == before


def test_source_hash_drift_for_same_literal_request_is_not_a_new_accept(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    _service(tmp_path, fixture)
    (tmp_path / fixture["artifact"]).write_text("changed bytes\n", encoding="utf-8")
    before = state_counts(tmp_path)

    drift = _service(tmp_path, fixture)

    assert drift["ok"] is False
    assert drift["error_code"] == "task_accept_task_request_conflict"
    assert drift["mutation_committed"] is False
    assert state_counts(tmp_path) == before


def test_precommit_failure_never_leaves_partial_business_rows(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    before = state_counts(tmp_path)

    def fail_before_final_gate(*args, **kwargs):
        raise RuntimeError("injected precommit failure")

    monkeypatch.setattr(
        "pcl.task_accept._validate_candidate_snapshot",
        fail_before_final_gate,
    )
    result = _service(tmp_path, fixture)

    assert result["ok"] is False
    assert result["mutation_committed"] is False
    assert result["error_code"] == "task_accept_internal_error"
    assert state_counts(tmp_path) == before


def test_abrupt_precommit_crash_rolls_back_business_and_retry_uses_orphan_safely(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    before = state_counts(tmp_path)

    crashed = _crash_command(tmp_path, fixture, "task_accept_before_sqlite_commit")

    assert crashed.returncode != 0
    assert state_counts(tmp_path) == before
    resumed = _service(tmp_path, fixture)
    assert resumed["status"] == "success"
    assert resumed["business_attempt_generation"] == 0


def test_stale_precommit_attempt_appends_successor_generation_and_resumes(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    crashed = _crash_command(tmp_path, fixture, "task_accept_before_sqlite_commit")
    assert crashed.returncode != 0
    assert main(
        [
            "--root",
            str(tmp_path),
            "goal",
            "create",
            "--title",
            "Unrelated prefix advance",
            "--json",
        ]
    ) == 0
    json_output(capsys)

    advanced = _service(tmp_path, fixture)
    assert advanced["ok"] is False
    assert advanced["mode"] == "stale_precommit_generation_advanced"
    assert advanced["status"] == "retry_required"
    assert advanced["business_attempt_generation"] == 1
    assert advanced["effects"]["generation_ledger_records_published"] == 1

    resumed = _service(tmp_path, fixture)

    assert resumed["ok"] is True
    assert resumed["status"] == "success"
    assert resumed["business_attempt_generation"] == 1

    replay = _service(tmp_path, fixture)
    assert replay["mode"] == "exact_replay_success"
    project_id = resumed["identity"]["project_instance_id"]
    locator = resumed["identity"]["request_locator"]
    historical_live = (
        tmp_path
        / ".project-loop"
        / "task-accept-recovery"
        / "v1"
        / "instances"
        / project_id
        / "requests"
        / locator
        / "live"
    )
    historical_begin = next(historical_live.glob("begin-*.json"))
    historical_begin.write_bytes(historical_begin.read_bytes() + b"tamper")
    blocked = _service(tmp_path, fixture)
    assert blocked["error_code"] == "task_accept_request_ledger_corrupt"
    assert blocked["mutation_committed"] is False


def test_generation_gap_or_fork_blocks_replay_without_effects(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    accepted = _service(tmp_path, fixture)
    project_id = accepted["identity"]["project_instance_id"]
    locator = accepted["identity"]["request_locator"]
    request_root = (
        tmp_path
        / ".project-loop"
        / "task-accept-recovery"
        / "v1"
        / "instances"
        / project_id
        / "requests"
        / locator
    )
    (request_root / "generation-0002").mkdir()
    before = state_counts(tmp_path)

    replay = _service(tmp_path, fixture)

    assert replay["ok"] is False
    assert replay["error_code"] == "task_accept_request_ledger_corrupt"
    assert replay["mutation_committed"] is False
    assert state_counts(tmp_path) == before


def test_superseded_acceptance_evidence_blocks_replay_as_noncurrent(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    accepted = _service(tmp_path, fixture)
    old_evidence = _accepted_evidence_id(tmp_path, accepted["authority"]["event_id"])
    replacement_path = tmp_path / "replacement.txt"
    replacement_path.write_text("replacement proof\n", encoding="utf-8")
    replacement = run_json(
        tmp_path,
        capsys,
        "evidence",
        "add",
        "--file",
        replacement_path.name,
        "--summary",
        "Replacement",
        "--copy",
    )
    run_json(
        tmp_path,
        capsys,
        "evidence",
        "supersede",
        old_evidence,
        "--with",
        replacement["evidence"]["id"],
        "--summary",
        "New current proof",
    )

    replay = _service(tmp_path, fixture)

    assert replay["ok"] is False
    assert replay["error_code"] == "task_accept_replay_not_current"
    assert replay["prior_acceptance_verified"] is False


def test_postcommit_render_failure_is_exit6_and_recovers_only_through_tail(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    monkeypatch.setattr(
        "pcl.task_accept._render_dashboard_with_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("render full")),
    )

    pending = _service(tmp_path, fixture)

    assert pending["ok"] is False
    assert pending["exit_code"] == 6
    assert pending["error_code"] == "task_accept_render_pending"
    assert pending["mutation_committed"] is True
    assert pending["safe_to_retry_original"] is False
    monkeypatch.undo()
    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 0
    json_output(capsys)
    replay = _service(tmp_path, fixture)
    assert replay["ok"] is True
    assert replay["status"] == "no_op"
    assert replay["effects"]["render_writes"] == 0


def test_postcommit_projection_failure_uses_dedicated_tail_recovery_generation(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)

    def pending_projection(*args, **kwargs) -> ProjectionResult:
        return ProjectionResult(
            committed=True,
            projection="pending",
            delivered=0,
            pending_count=1,
            first_pending_sequence=1,
            safe_next_action="pcl audit flush --json",
            error="injected projection failure",
        )

    monkeypatch.setattr("pcl.outbox.project_pending_events", pending_projection)
    pending = _service(tmp_path, fixture)

    assert pending["error_code"] == "task_accept_projection_pending"
    assert pending["mutation_committed"] is True
    assert pending["safe_to_retry_original"] is False
    committed_counts = state_counts(tmp_path)
    monkeypatch.undo()
    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 0
    recovery = json_output(capsys)["task_accept_tail_recovery"]
    assert recovery["mode"] == "accepted_authority_tail_recovery_success"
    assert recovery["status"] == "recovered"
    assert recovery["tail_recovery_generation"] == 1
    assert recovery["effects"]["markers_published"] == 6
    assert state_counts(tmp_path) == committed_counts
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    json_output(capsys)

    replay = _service(tmp_path, fixture)

    assert replay["status"] == "no_op"
    assert replay["tail_recovery_generation"] == 0
    assert replay["business_changed"] is False
    assert replay["effects"]["markers_published"] == 0


def test_postcommit_marker_failure_recovers_without_original_business_retry(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    monkeypatch.setattr(
        "pcl.task_accept._publish_accepted_marker",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("marker publish failed")),
    )

    pending = _service(tmp_path, fixture)

    assert pending["error_code"] == "task_accept_tail_pending"
    assert pending["mutation_committed"] is True
    assert pending["safe_retry_action"] == "pcl audit flush --json"
    committed_counts = state_counts(tmp_path)
    monkeypatch.undo()
    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 0
    recovery = json_output(capsys)["task_accept_tail_recovery"]
    assert recovery["status"] == "recovered"
    assert state_counts(tmp_path) == committed_counts
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    json_output(capsys)
    replay = _service(tmp_path, fixture)
    assert replay["status"] == "no_op"
    assert replay["tail_recovery_generation"] == 0


def test_commit_outcome_unknown_is_never_success_or_safe_original_retry(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)

    def commit_then_lose_ack(connection: MutationConnection) -> None:
        sqlite3.Connection.commit(connection)
        raise OSError("commit acknowledgement lost")

    monkeypatch.setattr(MutationConnection, "commit", commit_then_lose_ack)
    result = _service(tmp_path, fixture)

    assert result["ok"] is False
    assert result["exit_code"] == 6
    assert result["error_code"] == "task_accept_commit_outcome_unknown"
    assert result["status"] == "error"
    assert result["mutation_committed"] is False
    assert result["safe_to_retry_original"] is False
    assert result["safe_retry_action"] == "process_restart_and_inspect"
    committed_counts = state_counts(tmp_path)
    monkeypatch.undo()
    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 0
    recovery = json_output(capsys)["task_accept_tail_recovery"]
    assert recovery["status"] == "recovered"
    assert state_counts(tmp_path) == committed_counts
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    json_output(capsys)
    replay = _service(tmp_path, fixture)
    assert replay["status"] == "no_op"
    assert replay["tail_recovery_generation"] == 0


def test_abrupt_postcommit_crash_recovers_tail_without_business_reexecution(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys)
    before = state_counts(tmp_path)

    crashed = _crash_command(
        tmp_path,
        fixture,
        "after_sqlite_commit_before_projector",
    )

    assert crashed.returncode != 0
    committed = state_counts(tmp_path)
    assert committed["events"] > before["events"]
    assert committed["evidence"] == before["evidence"] + 1
    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 0
    recovery = json_output(capsys)["task_accept_tail_recovery"]
    assert recovery["status"] == "recovered"
    assert state_counts(tmp_path) == committed
    assert main(["--root", str(tmp_path), "render", "--json"]) == 0
    json_output(capsys)

    replay = _service(tmp_path, fixture)

    assert replay["status"] == "no_op"
    assert replay["business_changed"] is False
    assert replay["tail_recovery_generation"] == 0
