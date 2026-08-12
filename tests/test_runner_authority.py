from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from pcl.db import MutationConnection, connect, connect_mutation, initialize_database
from pcl.paths import ProjectPaths
from pcl.runner_authority import (
    MAX_RUNNER_FRAME_COUNT,
    RunnerAuthorityError,
    authority_gate_issues,
    build_authority_seal_draft,
    create_runner_authority_snapshot,
    hash_file,
    normalize_sidecar_policy,
    persist_runner_authority_anchor,
    verify_runner_authority_anchor,
)
from pcl.runner_execution_receipt import (
    MAX_RUNNER_FRAME_BYTES,
    _ParentFrameCollector,
    encode_child_frame,
    hash_argv,
    hash_cwd,
    hash_environment,
)


def _new_project(root: Path) -> ProjectPaths:
    paths = ProjectPaths(root)
    initialize_database(paths.db_path, paths.events_path)
    return paths


def _attempt_fixture(
    paths: ProjectPaths,
    *,
    prefix: str,
    attempt_id: str,
    attempt_index: int = 0,
    previous_attempt_id: str | None = None,
    previous_receipt_sha256: str | None = None,
    execution_instance_id: str = "execution-fixture",
) -> dict:
    summary_path = paths.root / f"{prefix}-summary.json"
    events_path = paths.root / f"{prefix}-events.jsonl"
    receipt_path = paths.root / f"{prefix}-receipt.json"
    result_path = paths.root / f"{prefix}-result.json"
    summary_path.write_text('{"summary":"parent fixture"}\n', encoding="utf-8")
    events_path.write_text('{"event":"parent fixture"}\n', encoding="utf-8")
    receipt = {"receipt_sha256": "sha256:" + "1" * 64}
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    result_path.write_text('{"status":"passed"}\n', encoding="utf-8")
    snapshot = create_runner_authority_snapshot(
        execution_instance_id=execution_instance_id,
        attempt_id=attempt_id,
        attempt_index=attempt_index,
        previous_attempt_id=previous_attempt_id,
        previous_receipt_sha256=previous_receipt_sha256,
        requested_argv_sha256=hash_argv(["python", "-c", "pass"]),
        spawned_argv_sha256=hash_argv(["python", "-c", "pass"]),
        cwd_identity_sha256=hash_cwd(paths.root),
        env_identity_sha256=hash_environment({"PCL_FIXTURE": "1"}),
        sidecar_policy=normalize_sidecar_policy(
            "required",
            summary_path=summary_path,
            events_path=events_path,
        ),
    )
    observations = {
        "spawn": {"status": "spawned", "error_kind": None},
        "exit_code": 0,
        "timed_out": False,
        "termination": {
            "requested": False,
            "method": "process_exit",
            "escalated": False,
            "term_sent": False,
            "kill_sent": False,
            "group_state": "gone",
            "leader_alive": False,
            "pipes_eof": True,
        },
        "streams": {"stdout_eof": True, "stderr_eof": True},
        "frames": {
            "sequence": 0,
            "root_sha256": "sha256:" + "0" * 64,
            "dropped_count": 0,
            "partial": False,
            "reader_error": False,
            "eof": True,
            "limit_exceeded": False,
        },
        "platform_capability": {"os": "posix", "status": "uncertain"},
    }
    draft = build_authority_seal_draft(
        snapshot=snapshot,
        observations=observations,
        sidecar_paths={"summary": summary_path, "events": events_path},
        receipt_path=receipt_path,
        receipt=receipt,
    )
    result_sha256 = hash_file(result_path)
    assert result_sha256 is not None
    return {
        "snapshot": snapshot.to_dict(),
        "draft": draft,
        "receipt_path": receipt_path,
        "summary_path": summary_path,
        "events_path": events_path,
        "result_path": result_path,
        "result_sha256": result_sha256,
        "receipt_sha256": receipt["receipt_sha256"],
    }


def _commit_fixture(paths: ProjectPaths, fixture: dict) -> dict:
    conn = connect_mutation(paths)
    try:
        result = persist_runner_authority_anchor(
            paths,
            draft=fixture["draft"],
            expected_inputs=fixture["snapshot"],
            result_binding={
                "path": fixture["result_path"].name,
                "sha256": fixture["result_sha256"],
                "kind": "finish_check_result",
            },
            target={"type": "runner_execution", "id": "execution-fixture"},
            conn=conn,
        )
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_parent_snapshot_anchor_is_authority_and_receipt_is_projection(tmp_path: Path) -> None:
    paths = _new_project(tmp_path)
    fixture = _attempt_fixture(paths, prefix="first", attempt_id="attempt-first")
    anchor = _commit_fixture(paths, fixture)

    verified = verify_runner_authority_anchor(
        paths,
        anchor_id=anchor["anchor_id"],
        expected_inputs=fixture["snapshot"],
    )
    assert verified["ok"] is True
    assert verified["evidence_id"] == anchor["evidence_id"]
    assert anchor["gate_issues"] == []
    assert fixture["draft"]["receipt_projection"]["file_sha256"] != fixture["receipt_sha256"]

    receipt = json.loads(fixture["receipt_path"].read_text(encoding="utf-8"))
    receipt["receipt_sha256"] = "sha256:" + "2" * 64
    fixture["receipt_path"].write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    assert verify_runner_authority_anchor(
        paths,
        anchor_id=anchor["anchor_id"],
        expected_inputs=fixture["snapshot"],
    )["ok"] is False


@pytest.mark.parametrize("mutation", ["replace", "truncate", "append", "symlink", "hardlink"])
def test_anchor_resolves_required_sidecars_and_rejects_artifact_mutations(
    tmp_path: Path, mutation: str
) -> None:
    paths = _new_project(tmp_path)
    fixture = _attempt_fixture(paths, prefix="case", attempt_id="attempt-case")
    anchor = _commit_fixture(paths, fixture)
    sidecar = fixture["summary_path"]

    if mutation == "replace":
        replacement = paths.root / "replacement.json"
        replacement.write_text("replacement\n", encoding="utf-8")
        replacement.replace(sidecar)
    elif mutation == "truncate":
        sidecar.write_bytes(b"")
    elif mutation == "append":
        with sidecar.open("ab") as stream:
            stream.write(b"append\n")
    elif mutation == "symlink":
        original = paths.root / "original-summary.json"
        sidecar.replace(original)
        try:
            sidecar.symlink_to(original)
        except OSError:
            pytest.skip("symlinks are unavailable")
    else:
        other = paths.root / "hardlink-summary.json"
        sidecar.replace(other)
        try:
            os.link(other, sidecar)
        except OSError:
            pytest.skip("hardlinks are unavailable")

    verification = verify_runner_authority_anchor(
        paths,
        anchor_id=anchor["anchor_id"],
        expected_inputs=fixture["snapshot"],
    )
    assert verification["ok"] is False
    assert any(issue.startswith("sidecar:summary:") for issue in verification["issues"])


def test_previous_pair_is_indivisible_and_attempt_chain_rejects_replay_and_gap(
    tmp_path: Path,
) -> None:
    paths = _new_project(tmp_path)
    first = _attempt_fixture(paths, prefix="first", attempt_id="attempt-first")
    first_anchor = _commit_fixture(paths, first)
    second = _attempt_fixture(
        paths,
        prefix="second",
        attempt_id="attempt-second",
        attempt_index=1,
        previous_attempt_id="wrong-attempt",
        previous_receipt_sha256=first["receipt_sha256"],
    )
    with pytest.raises(RunnerAuthorityError, match="Previous attempt") as error:
        _commit_fixture(paths, second)
    assert error.value.code == "runner_authority_previous_pair_mismatch"

    replay = _attempt_fixture(paths, prefix="replay", attempt_id="attempt-replay")
    with pytest.raises(RunnerAuthorityError) as replay_error:
        persist_runner_authority_anchor(
            paths,
            draft=first["draft"],
            expected_inputs=replay["snapshot"],
            result_binding={"path": replay["result_path"].name, "sha256": replay["result_sha256"]},
        )
    assert replay_error.value.code == "runner_authority_expected_input_mismatch"

    missing = _attempt_fixture(
        paths,
        prefix="missing",
        attempt_id="attempt-missing",
        attempt_index=1,
        previous_attempt_id="attempt-first",
        previous_receipt_sha256=first["receipt_sha256"],
        execution_instance_id="execution-missing",
    )
    # A distinct execution instance proves the missing-predecessor gate.
    with pytest.raises(RunnerAuthorityError) as gap_error:
        persist_runner_authority_anchor(
            paths,
            draft=missing["draft"],
            expected_inputs=missing["snapshot"],
            result_binding={"path": missing["result_path"].name, "sha256": missing["result_sha256"]},
        )
    assert gap_error.value.code == "runner_authority_anchor_gap"
    assert first_anchor["anchor_id"].startswith("RA-")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("timed_out", True, "contradiction:timeout_exit_code"),
        ("frame_count", MAX_RUNNER_FRAME_COUNT + 1, "gate:frame_count_exceeded"),
        ("dropped", 1, "gate:frames_dropped"),
        ("partial", True, "gate:partial_frame"),
        ("reader_error", True, "gate:frame_reader_error"),
        ("eof", False, "gate:frame_eof_missing"),
    ],
)
def test_parent_observation_gates_are_fail_closed(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    paths = _new_project(tmp_path)
    fixture = _attempt_fixture(paths, prefix="gates", attempt_id="attempt-gates")
    observations = deepcopy(fixture["draft"]["observations"])
    if field == "timed_out":
        observations["timed_out"] = value
    elif field == "frame_count":
        observations["frames"]["sequence"] = value
    elif field == "dropped":
        observations["frames"]["dropped_count"] = value
    elif field == "partial":
        observations["frames"]["partial"] = value
    elif field == "reader_error":
        observations["frames"]["reader_error"] = value
    else:
        observations["frames"]["eof"] = value
    issues = authority_gate_issues(
        snapshot=fixture["snapshot"],
        observations=observations,
        sidecars=fixture["draft"]["sidecars"],
    )
    assert expected in issues
    if expected.startswith("contradiction:"):
        broken = deepcopy(fixture["draft"].to_dict())
        broken["observations"] = observations
        broken["gate_issues"] = issues
        broken["canonical_hashes"]["observations_sha256"] = "sha256:" + "0" * 64
        with pytest.raises(RunnerAuthorityError):
            persist_runner_authority_anchor(
                paths,
                draft=broken,
                expected_inputs=fixture["snapshot"],
                result_binding={"path": fixture["result_path"].name, "sha256": fixture["result_sha256"]},
            )


def test_frame_collector_enforces_limit_and_partial_invalid_drop_eof_gates() -> None:
    collector = _ParentFrameCollector()
    frame = encode_child_frame({"kind": "parent-fixture"})
    for _ in range(MAX_RUNNER_FRAME_COUNT + 1):
        collector.feed(frame)
    collector.feed(b"not-json\n")
    collector.feed(b"{")
    collector.finish()
    assert collector.sequence == MAX_RUNNER_FRAME_COUNT
    assert collector.limit_exceeded is True
    assert collector.dropped_count > 0
    assert collector.partial_frame is True
    assert collector.frames_eof is True
    assert len(frame) <= MAX_RUNNER_FRAME_BYTES


def test_frame_collector_parses_complete_frames_before_bounding_residual_buffer() -> None:
    collector = _ParentFrameCollector()
    frame = encode_child_frame({"kind": "parent-fixture", "padding": "x" * 96})
    frame_count = 1 + (65_536 // len(frame))
    chunk = frame * frame_count
    assert 32_768 < len(chunk) <= 65_536 + len(frame)

    collector.feed(chunk)
    collector.finish()

    assert collector.sequence == frame_count
    assert collector.dropped_count == 0
    assert collector.partial_frame is False
    assert collector.frames_eof is True


@pytest.mark.parametrize("fault_point", [
    "runner_authority_after_evidence",
    "runner_authority_before_event",
    "runner_authority_after_event_before_commit",
])
def test_anchor_write_crash_points_leave_no_partial_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault_point: str
) -> None:
    paths = _new_project(tmp_path)
    fixture = _attempt_fixture(paths, prefix="crash", attempt_id="attempt-crash")

    def crash(point: str) -> None:
        if point == fault_point:
            raise RuntimeError(point)

    monkeypatch.setattr("pcl.runner_authority.crash_if_requested", crash)
    with pytest.raises(RuntimeError, match=fault_point):
        _commit_fixture(paths, fixture)
    conn = connect(paths.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'runner_authority_anchor_committed'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_anchor_write_crash_after_commit_retains_one_verifiable_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _new_project(tmp_path)
    fixture = _attempt_fixture(paths, prefix="after-commit", attempt_id="attempt-after-commit")
    original_commit = MutationConnection.commit

    def commit_then_crash(connection: MutationConnection) -> None:
        original_commit(connection)
        raise RuntimeError("after_sqlite_commit")

    monkeypatch.setattr(MutationConnection, "commit", commit_then_crash)
    with pytest.raises(RuntimeError, match="after_sqlite_commit"):
        _commit_fixture(paths, fixture)
    conn = connect(paths.db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'runner_authority_anchor_committed'"
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()
    # The anchor ID is recovered from the committed event, not from a mutated
    # receipt or a caller-supplied sidecar path.
    conn = connect(paths.db_path)
    try:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM events WHERE event_type = 'runner_authority_anchor_committed'"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert verify_runner_authority_anchor(
        paths,
        anchor_id=payload["anchor_id"],
        expected_inputs=fixture["snapshot"],
    )["ok"] is True


def test_timeout_and_spawn_group_contradictions_are_rejected() -> None:
    snapshot = {
        "sidecar_policy": {"mode": "required"},
    }
    timeout_issues = authority_gate_issues(
        snapshot=snapshot,
        observations={
            "spawn": {"status": "spawned"},
            "exit_code": None,
            "timed_out": True,
            "termination": {"requested": True, "method": "process_exit", "pipes_eof": True, "group_state": "gone"},
            "streams": {"stdout_eof": True, "stderr_eof": True},
            "frames": {"eof": True, "sequence": 0, "dropped_count": 0},
        },
        sidecars={},
    )
    assert "contradiction:timeout_process_exit_method" in timeout_issues

    spawn_issues = authority_gate_issues(
        snapshot={"sidecar_policy": {"mode": "not_applicable"}},
        observations={
            "spawn": {"status": "spawned"},
            "timed_out": False,
            "termination": {"requested": False, "pipes_eof": False, "group_state": "not_started"},
            "streams": {"stdout_eof": False, "stderr_eof": False},
            "frames": {"eof": True, "sequence": 0, "dropped_count": 0},
        },
        sidecars={},
    )
    assert "contradiction:spawned_not_started" in spawn_issues
