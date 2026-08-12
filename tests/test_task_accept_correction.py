from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re
import subprocess
import sys

from pcl.cli import main
from pcl.db import connect
from pcl.task_accept import accept_task
from pcl.paths import resolve_paths

from task_accept_helpers import accept_args, json_output, prepare_acceptance, run_json, state_counts


EFFECT_KEYS = {
    "business_attempt_ledger_records_published",
    "business_db_rows_deleted",
    "business_db_rows_inserted",
    "business_db_rows_updated",
    "copies_published",
    "db_mutations_total",
    "durable_recovery_records_published",
    "events_appended",
    "evidence_links_inserted",
    "evidence_rows_inserted",
    "feature_status_updates",
    "generation_ledger_records_published",
    "live_generation_records_published",
    "markers_published",
    "outbox_records_appended",
    "projection_records_delivered",
    "render_writes",
    "reservation_index_records_published",
    "tail_db_rows_deleted",
    "tail_db_rows_inserted",
    "tail_db_rows_updated",
    "tail_recovery_ledger_records_published",
    "task_rows_updated",
    "teardown_receipts_published",
    "test_rows_updated",
}


def _service(root: Path, fixture: dict) -> dict:
    return accept_task(
        resolve_paths(root),
        task_id=fixture["task_id"],
        artifact_path=fixture["artifact"],
        command="pytest -q",
        summary="Acceptance verified",
        copy_files=True,
        test_ids=fixture["test_ids"],
    )


def test_final_reseal_blocks_external_member_tamper_before_commit(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    before = state_counts(tmp_path)
    from pcl import task_accept

    original = task_accept._verify_final_rows_and_events

    def tamper_after_final_rows(*args, **kwargs):
        original(*args, **kwargs)
        members = list(
            (tmp_path / ".project-loop" / "evidence" / "adhoc-files").glob(
                "e-*/sha256-*.artifact"
            )
        )
        assert len(members) == 1
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'tampered externally\\n')",
                str(members[0]),
            ],
            check=True,
        )

    monkeypatch.setattr(task_accept, "_verify_final_rows_and_events", tamper_after_final_rows)

    result = _service(tmp_path, fixture)

    assert result["ok"] is False
    assert result["mutation_committed"] is False
    assert result["error_code"] == "task_accept_current_proof_invalid"
    assert state_counts(tmp_path) == before
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (fixture["task_id"],)
        ).fetchone()["status"] == "in_progress"
        assert conn.execute(
            "SELECT status FROM features WHERE id = ?", (fixture["feature_id"],)
        ).fetchone()["status"] != "done"
    finally:
        conn.close()


def test_linux_root_rebind_is_typed_noncommit_before_physical_commit(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    displaced = tmp_path / "displaced"
    fixture = prepare_acceptance(project, capsys, test_count=2)
    before = state_counts(project)
    from pcl import task_accept

    original = task_accept._verify_final_rows_and_events

    def rebind_after_final_rows(*args, **kwargs):
        original(*args, **kwargs)
        project.rename(displaced)
        project.mkdir()
        (project / ".project-loop").mkdir()

    monkeypatch.setattr(
        task_accept,
        "_verify_final_rows_and_events",
        rebind_after_final_rows,
    )
    monkeypatch.setattr(
        task_accept,
        "_requires_original_path_binding_at_commit",
        lambda: True,
    )

    result = _service(project, fixture)

    assert result["ok"] is False
    assert result["mutation_committed"] is False
    assert result["error_code"] == "task_accept_root_changed"
    assert result["safe_to_retry_original"] is False
    assert state_counts(displaced) == before
    assert not (project / ".project-loop" / "project.db").exists()


def test_public_cli_replay_allows_preexisting_task_supporting_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    supporting_path = tmp_path / "supporting.txt"
    supporting_path.write_text("pre-existing task context\n", encoding="utf-8")
    supporting = run_json(
        tmp_path,
        capsys,
        "evidence",
        "add",
        "--file",
        supporting_path.name,
        "--summary",
        "Existing Task support",
        "--copy",
        "--task",
        fixture["task_id"],
    )
    assert supporting["evidence"]["linked_task_id"] == fixture["task_id"]

    fresh = run_json(tmp_path, capsys, *accept_args(fixture))
    before = state_counts(tmp_path)
    replay = run_json(tmp_path, capsys, *accept_args(fixture))

    assert fresh["mode"] == "fresh_success"
    assert replay["mode"] == "exact_replay_success"
    assert replay["status"] == "no_op"
    assert replay["changed"] is False
    assert set(replay["effects"]) == EFFECT_KEYS
    assert set(replay["effects"].values()) == {0}
    assert state_counts(tmp_path) == before


def test_tail_recovery_rechecks_live_p0b_before_publishing_marker(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    monkeypatch.setattr(
        "pcl.task_accept._publish_accepted_marker",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("marker failure")),
    )
    pending = _service(tmp_path, fixture)
    assert pending["mutation_committed"] is True
    assert pending["exit_code"] == 6
    monkeypatch.undo()

    run_json(
        tmp_path,
        capsys,
        "defect",
        "open",
        "--feature",
        fixture["feature_id"],
        "--severity",
        "high",
        "--expected",
        "accepted proof remains healthy",
        "--actual",
        "new blocker",
    )
    recovery_root = tmp_path / ".project-loop" / "task-accept-recovery" / "v1"
    before_files = sorted(path.relative_to(recovery_root) for path in recovery_root.rglob("*") if path.is_file())

    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 6
    payload = json_output(capsys)
    recovery = payload["task_accept_tail_recovery"]
    assert recovery["mode"] == "accepted_authority_tail_recovery_error"
    assert recovery["mutation_committed"] is False
    assert recovery["validation"]["status"] == "blocked"
    assert recovery["effects"]["business_db_rows_inserted"] == 0
    assert recovery["effects"]["markers_published"] == 0
    assert sorted(path.relative_to(recovery_root) for path in recovery_root.rglob("*") if path.is_file()) == before_files


def test_fresh_publishes_m2_framed_authority_and_replay_publishes_zero(
    tmp_path: Path,
    capsys,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)

    fresh = run_json(tmp_path, capsys, *accept_args(fixture))
    recovery_root = tmp_path / ".project-loop" / "task-accept-recovery" / "v1"
    records = sorted(path for path in recovery_root.rglob("*") if path.is_file())

    assert len(records) == 31
    assert all(path.read_bytes().startswith(b"PCLF1") for path in records)
    roles = Counter()
    for path in records:
        match = re.fullmatch(r"(.+)-([0-9a-f]{64})\.json", path.name)
        assert match is not None
        assert hashlib.sha256(path.read_bytes()).hexdigest() == match.group(2)
        roles[match.group(1)] += 1
    assert roles == Counter(
        {
            "accepted": 1,
            "begin": 1,
            "evidence": 1,
            "evidence-binding": 1,
            "event": 6,
            "feature-binding": 1,
            "generation-manifest": 1,
            "ledger-reserved": 1,
            "ledger-sealed": 1,
            "outbox": 6,
            "plan-binding": 1,
            "projection": 1,
            "render": 1,
            "request-binding": 1,
            "reservation-manifest": 1,
            "sqlite-commit": 1,
            "tail": 1,
            "task-binding": 1,
            "teardown": 1,
            "test-binding": 2,
        }
    )
    assert fresh["effects"]["reservation_index_records_published"] == 14
    assert fresh["effects"]["live_generation_records_published"] == 15
    assert fresh["effects"]["generation_ledger_records_published"] == 2
    assert fresh["effects"]["markers_published"] == 31
    before = {path: path.read_bytes() for path in records}

    replay = run_json(tmp_path, capsys, *accept_args(fixture))

    assert replay["mode"] == "exact_replay_success"
    assert {path: path.read_bytes() for path in records} == before
    assert set(replay["effects"].values()) == {0}


def test_m5_envelope_version_modes_effects_and_boolean_commit_contract(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    fresh = run_json(tmp_path, capsys, *accept_args(fixture))

    assert fresh["schema_version"] == "task-accept-envelope/v1"
    assert fresh["mode"] == "fresh_success"
    assert fresh["status"] == "success"
    assert set(fresh["effects"]) == EFFECT_KEYS
    assert type(fresh["mutation_committed"]) is bool

    from pcl.db import MutationConnection
    import sqlite3

    second_root = tmp_path / "unknown"
    second = prepare_acceptance(second_root, capsys, test_count=2)

    def commit_then_lose_ack(connection: MutationConnection) -> None:
        sqlite3.Connection.commit(connection)
        raise OSError("commit acknowledgement lost")

    monkeypatch.setattr(MutationConnection, "commit", commit_then_lose_ack)
    unknown = _service(second_root, second)
    assert unknown["mode"] == "fresh_postcommit_tail_error"
    assert unknown["status"] == "error"
    assert unknown["mutation_committed"] is False
    assert unknown["safe_to_retry_original"] is False


def test_m5_human_lines_are_exact_and_use_one_stream(tmp_path: Path, capsys) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)

    assert main(["--root", str(tmp_path), *accept_args(fixture)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("OK task_accept fresh_success: Task ")
    assert captured.out.endswith("]\n")

    assert main(["--root", str(tmp_path), *accept_args(fixture)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("OK task_accept exact_replay_success: Task ")
    assert captured.out.endswith("]\n")
