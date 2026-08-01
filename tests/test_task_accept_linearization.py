from __future__ import annotations

from collections import Counter
import inspect
import json
from pathlib import Path
import subprocess
import sys

import pytest

from pcl.db import MutationConnection, connect
from pcl.paths import resolve_paths
from pcl.task_accept import (
    accept_task,
    task_accept_human_line,
    validate_task_accept_envelope,
)
from pcl.tasks import task_terminal_readiness_for_row
from pcl.validators import validate_project

from task_accept_helpers import accept_args, prepare_acceptance, state_counts


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


def _copied_member(root: Path) -> Path:
    members = list(
        (root / ".project-loop" / "evidence" / "adhoc-files").glob(
            "e-*/sha256-*.artifact"
        )
    )
    assert len(members) == 1
    return members[0]


def _super_commit_line() -> int:
    lines, start = inspect.getsourcelines(MutationConnection.commit)
    offsets = [index for index, line in enumerate(lines) if "super().commit()" in line]
    assert offsets == [6]
    return start + offsets[0]


def _external_tamper(path: Path, variant: str) -> None:
    if variant == "rewrite":
        source = (
            "from pathlib import Path; import sys; "
            "Path(sys.argv[1]).write_bytes(b'post-V rewrite corruption\\n')"
        )
    else:
        source = (
            "from pathlib import Path; import os, sys; "
            "p=Path(sys.argv[1]); q=p.with_name(p.name+'.replacement'); "
            "q.write_bytes(b'post-V rename corruption\\n'); os.replace(q,p)"
        )
    subprocess.run([sys.executable, "-c", source, str(path)], check=True)


@pytest.mark.parametrize("variant", ["rewrite", "rename"])
def test_post_reseal_pre_physical_commit_corruption_is_isolated(
    tmp_path: Path,
    capsys,
    variant: str,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    before = state_counts(tmp_path)
    target_line = _super_commit_line()
    observed = {"post_reseal_boundary": False}

    def trace(frame, event, arg):
        del arg
        if (
            event == "line"
            and frame.f_code is MutationConnection.commit.__code__
            and frame.f_lineno == target_line
            and frame.f_locals["self"]._precommit_guard is not None
            and not observed["post_reseal_boundary"]
        ):
            observed["post_reseal_boundary"] = True
            _external_tamper(_copied_member(tmp_path), variant)
        return trace

    sys.settrace(trace)
    try:
        from pcl.cli import main

        exit_code = main(
            ["--root", str(tmp_path), *accept_args(fixture), "--json"]
        )
    finally:
        sys.settrace(None)
    result = json.loads(capsys.readouterr().out)

    assert observed["post_reseal_boundary"] is True
    assert exit_code == 6
    assert result["ok"] is False
    assert result["mode"] == "fresh_postcommit_tail_error"
    assert result["error_code"] == "task_accept_post_acceptance_corruption"
    assert result["phase"] == "post_acceptance_corruption"
    assert result["pending_tail"]["stage"] == "corrupt"
    assert result["mutation_committed"] is True
    assert result["exit_code"] == 6
    assert result["safe_retry_action"] == "pcl audit flush --json"
    assert task_accept_human_line(result) == (
        "ERROR task_accept task_accept_post_acceptance_corruption: "
        "Acceptance committed at the final reseal, but immediate post-acceptance "
        "corruption was detected. [action=pcl audit flush --json]"
    )

    after = state_counts(tmp_path)
    assert after["evidence"] == before["evidence"] + 1
    assert after["evidence_links"] == before["evidence_links"] + 4
    assert after["events"] == before["events"] + 6
    assert after["outbox_records"] == before["outbox_records"] + 6
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (fixture["task_id"],)
        ).fetchone()["status"] == "done"
        assert conn.execute(
            "SELECT status FROM features WHERE id = ?", (fixture["feature_id"],)
        ).fetchone()["status"] == "done"
        assert {
            row["status"]
            for row in conn.execute(
                "SELECT status FROM test_cases WHERE id IN (?, ?)",
                tuple(fixture["test_ids"]),
            ).fetchall()
        } == {"passing"}
        assert conn.execute(
            "SELECT COUNT(*) FROM outbox_records WHERE delivered_at IS NULL"
        ).fetchone()[0] == 6
    finally:
        conn.close()

    recovery_root = tmp_path / ".project-loop" / "task-accept-recovery" / "v1"
    roles = Counter(path.name.rsplit("-", 1)[0] for path in recovery_root.rglob("*.json"))
    assert sum(roles.values()) == 24
    assert roles["accepted"] == 0
    assert roles["projection"] == 0
    assert roles["render"] == 0
    assert roles["teardown"] == 0
    assert roles["tail"] == 0
    assert roles["generation-manifest"] == 0
    assert roles["ledger-sealed"] == 0

    from pcl.cli import main

    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 6
    recovery = json.loads(capsys.readouterr().out)["task_accept_tail_recovery"]
    validate_task_accept_envelope(recovery)
    assert recovery["mode"] == "accepted_authority_tail_recovery_error"
    assert recovery["error_code"] == "task_accept_post_acceptance_corruption"
    assert recovery["effects"] == {key: 0 for key in recovery["effects"]}
    assert recovery["validation"]["status"] == "blocked"


def test_corruption_after_complete_is_high_and_blocks_consumers(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    fixture = prepare_acceptance(tmp_path, capsys, test_count=2)
    from pcl import task_accept

    original_publish = task_accept._publish_m2_postcommit_authority

    def tamper_after_immediate_check(generation):
        _external_tamper(_copied_member(tmp_path), "rewrite")
        return original_publish(generation)

    monkeypatch.setattr(
        task_accept,
        "_publish_m2_postcommit_authority",
        tamper_after_immediate_check,
    )
    accepted = _service(tmp_path, fixture)
    assert accepted["mode"] == "fresh_postcommit_tail_error"
    assert accepted["error_code"] == "task_accept_post_acceptance_corruption"
    assert accepted["phase"] == "post_acceptance_corruption"
    assert accepted["mutation_committed"] is True
    assert accepted["effects"]["markers_published"] == 25
    assert accepted["receipts"]["render_status"] == "not_started"
    assert accepted["pending_tail"]["render_pending"] is False
    validate_task_accept_envelope(accepted)
    contradictory = json.loads(json.dumps(accepted))
    contradictory["receipts"]["render_status"] = "pending"
    with pytest.raises(ValueError, match="pending render receipt mismatch"):
        validate_task_accept_envelope(contradictory)
    before = state_counts(tmp_path)

    copied_member = _copied_member(tmp_path)
    corrupted_bytes = copied_member.read_bytes()
    immutable_surfaces = {
        path: path.read_bytes()
        for path in (
            tmp_path / ".project-loop" / "events.jsonl",
            tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json",
            tmp_path / ".project-loop" / "dashboard" / "dashboard.html",
        )
    }

    from pcl.cli import main

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    validation = json.loads(capsys.readouterr().out)
    integrity = [
        finding
        for finding in validation["findings"]
        if finding["code"] == "evidence_adhoc_copy_hash_mismatch"
    ]
    assert len(integrity) == 1
    assert integrity[0]["severity"] == "error"
    assert state_counts(tmp_path) == before
    assert {path: path.read_bytes() for path in immutable_surfaces} == immutable_surfaces

    assert main(["--root", str(tmp_path), "doctor", "--json"]) == 1
    doctor = json.loads(capsys.readouterr().out)
    assert any(
        finding["code"] == "evidence_adhoc_copy_hash_mismatch"
        and finding["severity"] == "error"
        for finding in doctor["findings"]
    )
    assert state_counts(tmp_path) == before
    assert {path: path.read_bytes() for path in immutable_surfaces} == immutable_surfaces

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        strict = validate_project(resolve_paths(tmp_path), strict=True, connection=conn)
        task = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (fixture["task_id"],)
        ).fetchone()
        assert task is not None
        readiness = task_terminal_readiness_for_row(
            resolve_paths(tmp_path),
            conn,
            dict(task),
            source="post_acceptance_corruption_test",
            formal_findings=list(strict.findings),
        )
    finally:
        conn.close()
    assert readiness["terminal_allowed"] is False

    replay = _service(tmp_path, fixture)
    assert replay["error_code"] == "task_accept_replay_not_current"
    assert replay["mutation_committed"] is False
    assert state_counts(tmp_path) == before

    assert main(["--root", str(tmp_path), "audit", "flush", "--json"]) == 6
    recovery = json.loads(capsys.readouterr().out)["task_accept_tail_recovery"]
    validate_task_accept_envelope(recovery)
    assert recovery["mode"] == "accepted_authority_tail_recovery_error"
    assert recovery["error_code"] == "task_accept_post_acceptance_corruption"
    assert recovery["validation"]["status"] == "blocked"
    assert state_counts(tmp_path) == before
    assert copied_member.read_bytes() == corrupted_bytes
