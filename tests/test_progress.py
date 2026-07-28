from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from pcl.cli import main
from pcl.db import connect


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_git_project(root: Path, capsys, *, task_count: int = 1) -> None:
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "pcl@example.test")
    _git(root, "config", "user.name", "PCL Test")
    (root / "README.md").write_text("progress fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "baseline")
    assert main(["init", "--target", str(root), "--json"]) == 0
    _json(capsys)
    assert main([
        "--root", str(root), "goal", "create", "--title", "Progress goal",
    ]) == 0
    for index in range(task_count):
        assert main([
            "--root", str(root), "task", "create",
            "--title", f"Progress task {index + 1}", "--goal", "G-0001",
        ]) == 0
    capsys.readouterr()


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "evidence": int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "outbox": int(conn.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0]),
        }
    finally:
        conn.close()


def _add_task_evidence(root: Path, capsys, *, task_id: str) -> str:
    proof = root / f"proof-{task_id}.txt"
    proof.write_text(f"proof for {task_id}\n", encoding="utf-8")
    assert main([
        "--root", str(root), "evidence", "add",
        "--file", str(proof),
        "--summary", f"Proof for {task_id}",
        "--command", "pytest -q",
        "--copy",
        "--task", task_id,
        "--json",
    ]) == 0
    return str(_json(capsys)["evidence"]["id"])


def _record_progress(
    root: Path,
    capsys,
    *,
    milestone: str,
    status: str = "started",
    task_id: str = "T-0001",
    extra: list[str] | None = None,
) -> dict:
    args = [
        "--root", str(root), "progress", "record",
        "--task", task_id,
        "--milestone", milestone,
        "--status", status,
        *(extra or []),
        "--json",
    ]
    assert main(args) == 0
    return _json(capsys)["progress"]


def test_progress_record_writes_hash_anchored_target_receipt_with_optional_bindings(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"
    _init_git_project(root, capsys)
    evidence_id = _add_task_evidence(root, capsys, task_id="T-0001")

    progress = _record_progress(
        root,
        capsys,
        milestone="P0-6 implementation",
        status="completed",
        extra=[
            "--evidence-id", evidence_id,
            "--blocker", "Operator review remains.",
            "--cockpit-task-id", "task-123",
            "--cockpit-report-seq", "7",
            "--cockpit-report-ref", "report:7",
            "--ci-provider", "github-actions",
            "--ci-run-id", "123456",
            "--ci-run-url", "https://example.test/runs/123456",
        ],
    )

    receipt = progress["receipt"]
    binding = receipt["execution_binding"]
    assert receipt["contract_version"] == "progress-receipt/v1"
    assert receipt["receipt_id"].startswith("pr-sha256:")
    assert receipt["target"] == {"type": "task", "id": "T-0001"}
    assert receipt["latest_valid_evidence"]["evidence_id"] == evidence_id
    assert receipt["residual_blockers"] == ["Operator review remains."]
    assert binding["contract_version"] == "execution-binding/v1"
    assert binding["canonical_root"] == str(root.resolve())
    assert binding["execution_root"] == str(root.resolve())
    assert binding["git"]["worktree_root"] == str(root.resolve())
    assert binding["git"]["common_dir"] == str((root / ".git").resolve())
    assert binding["git"]["head_revision"] == _git(root, "rev-parse", "HEAD")
    assert binding["git"]["branch"] == "main"
    assert binding["git"]["detached"] is False
    assert binding["git"]["relationship"] == "same_worktree"
    assert binding["cockpit"] == {
        "task_id": "task-123",
        "report_sequence": 7,
        "report_ref": "report:7",
    }
    assert binding["ci"] == {
        "provider": "github-actions",
        "run_id": "123456",
        "run_url": "https://example.test/runs/123456",
    }

    artifact = root / progress["artifact_path"]
    content = artifact.read_bytes()
    assert hashlib.sha256(content).hexdigest() == progress["artifact_sha256"]
    assert json.loads(content)["receipt_id"] == receipt["receipt_id"]

    conn = connect(root / ".project-loop" / "project.db")
    try:
        evidence = conn.execute(
            "SELECT type, path FROM evidence WHERE id = ?",
            (progress["evidence_id"],),
        ).fetchone()
        link = conn.execute(
            """
            SELECT target_type, target_id, link_role
            FROM evidence_links WHERE evidence_id = ?
            """,
            (progress["evidence_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT event_type, entity_type, entity_id, payload_json FROM events WHERE id = ?",
            (progress["event_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert dict(evidence) == {
        "type": "progress_receipt",
        "path": progress["artifact_path"],
    }
    assert dict(link) == {
        "target_type": "task",
        "target_id": "T-0001",
        "link_role": "progress_receipt",
    }
    assert dict(event) | {"payload_json": None} == {
        "event_type": "progress_receipt_recorded",
        "entity_type": "task",
        "entity_id": "T-0001",
        "payload_json": None,
    }
    event_payload = json.loads(event["payload_json"])
    assert event_payload["artifact_sha256"] == progress["artifact_sha256"]
    assert event_payload["evidence_id"] == progress["evidence_id"]
    assert event_payload["receipt_id"] == receipt["receipt_id"]


def test_progress_binding_accepts_same_common_dir_linked_detached_worktree(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"
    linked = tmp_path / "linked"
    _init_git_project(root, capsys)
    _git(root, "worktree", "add", "--detach", str(linked), "HEAD")

    progress = _record_progress(
        root,
        capsys,
        milestone="Linked worktree implementation",
        extra=["--execution-root", str(linked)],
    )

    binding = progress["receipt"]["execution_binding"]
    assert binding["canonical_root"] == str(root.resolve())
    assert binding["execution_root"] == str(linked.resolve())
    assert binding["git"]["worktree_root"] == str(linked.resolve())
    assert binding["git"]["common_dir"] == str((root / ".git").resolve())
    assert binding["git"]["branch"] is None
    assert binding["git"]["detached"] is True
    assert binding["git"]["relationship"] == "linked_worktree"


@pytest.mark.parametrize(
    "extra",
    [
        ["--status", "blocked"],
        ["--cockpit-report-seq", "2"],
        ["--cockpit-report-ref", "report:2"],
        ["--ci-provider", "github-actions"],
        ["--ci-run-id", "1234"],
    ],
)
def test_progress_invalid_groups_fail_closed_without_mutation(
    tmp_path: Path,
    capsys,
    extra: list[str],
) -> None:
    root = tmp_path / "project"
    _init_git_project(root, capsys)
    before = _counts(root)
    args = [
        "--root", str(root), "progress", "record",
        "--task", "T-0001",
        "--milestone", "Invalid progress",
        "--status", "started",
        *extra,
        "--json",
    ]

    assert main(args) == 2
    payload = _json(capsys)

    assert payload["error"]["code"] == "invalid_input"
    assert _counts(root) == before
    assert not (root / ".project-loop" / "evidence" / "progress-receipts").exists()


def test_progress_unrelated_execution_root_and_wrong_target_evidence_fail_closed(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"
    unrelated = tmp_path / "unrelated"
    _init_git_project(root, capsys, task_count=2)
    unrelated.mkdir()
    _git(unrelated, "init", "-b", "other")
    _git(unrelated, "config", "user.email", "pcl@example.test")
    _git(unrelated, "config", "user.name", "PCL Test")
    (unrelated / "README.md").write_text("other\n", encoding="utf-8")
    _git(unrelated, "add", "README.md")
    _git(unrelated, "commit", "-m", "other")
    evidence_id = _add_task_evidence(root, capsys, task_id="T-0002")
    before = _counts(root)

    assert main([
        "--root", str(root), "progress", "record",
        "--task", "T-0001",
        "--milestone", "Unrelated",
        "--status", "started",
        "--execution-root", str(unrelated),
        "--json",
    ]) == 2
    unrelated_payload = _json(capsys)
    assert unrelated_payload["error"]["code"] == "execution_binding_unrelated_root"
    assert _counts(root) == before

    assert main([
        "--root", str(root), "progress", "record",
        "--task", "T-0001",
        "--milestone", "Wrong evidence",
        "--status", "completed",
        "--evidence-id", evidence_id,
        "--json",
    ]) == 2
    evidence_payload = _json(capsys)
    assert evidence_payload["error"]["code"] == "progress_evidence_target_mismatch"
    assert _counts(root) == before


def test_resume_and_context_prioritize_progress_without_promoting_verified_claims(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"
    _init_git_project(root, capsys)

    assert main([
        "--root", str(root), "resume", "--target", "T-0001", "--json",
    ]) == 0
    without_resume = _json(capsys)["handoff_packet"]
    assert "progress" not in without_resume
    assert main([
        "--root", str(root), "context", "pack", "--task", "T-0001", "--json",
    ]) == 0
    without_context = _json(capsys)["context_pack"]
    assert "progress" not in without_context
    assert "progress_orientation" not in without_context["included_sections"]

    progress = _record_progress(
        root,
        capsys,
        milestone="Waiting for operator",
        status="blocked",
        extra=["--blocker", "Human approval is required."],
    )
    assert main([
        "--root", str(root), "resume", "--target", "T-0001", "--json",
    ]) == 0
    handoff = _json(capsys)["handoff_packet"]
    assert handoff["progress"]["status"] == "valid"
    assert handoff["progress"]["receipt"]["milestone"] == "Waiting for operator"
    assert handoff["summary"].startswith(
        "Progress milestone Waiting for operator is blocked"
    )
    assert handoff["current_state"] == "TODO"
    assert handoff["verified"] == []
    assert "Human approval is required." in handoff["blockers"]
    assert any(
        item["ref"] == f"evidence:{progress['evidence_id']}"
        and item["kind"] == "progress-receipt/v1"
        for item in handoff["context_refs"]
    )

    assert main([
        "--root", str(root), "context", "pack", "--task", "T-0001",
        "--max-tokens", "350", "--json",
    ]) == 0
    context = _json(capsys)["context_pack"]
    assert context["progress"]["status"] == "valid"
    assert context["progress"]["receipt"]["milestone"] == "Waiting for operator"
    assert "progress_orientation" in context["required_sections"]
    assert "progress_orientation" in context["included_sections"]
    assert "## Progress Orientation" in context["markdown"]


def test_corrupt_latest_progress_is_surfaced_without_silent_fallback(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "project"
    _init_git_project(root, capsys)
    older = _record_progress(root, capsys, milestone="Older valid milestone")
    latest = _record_progress(
        root,
        capsys,
        milestone="Latest corrupt milestone",
        status="blocked",
        extra=["--blocker", "Latest blocker."],
    )
    (root / latest["artifact_path"]).write_text("{}\n", encoding="utf-8")

    assert main([
        "--root", str(root), "resume", "--target", "T-0001", "--json",
    ]) == 0
    handoff = _json(capsys)["handoff_packet"]
    assert handoff["progress"]["status"] == "invalid"
    assert handoff["progress"]["evidence_id"] == latest["evidence_id"]
    assert handoff["progress"]["artifact_health"] == "artifact_hash_mismatch"
    assert "Older valid milestone" not in handoff["summary"]
    assert f"evidence:{older['evidence_id']}" not in {
        item["ref"]
        for item in handoff["context_refs"]
        if item["kind"] == "progress-receipt/v1"
    }

    assert main([
        "--root", str(root), "context", "pack", "--task", "T-0001", "--json",
    ]) == 0
    context = _json(capsys)["context_pack"]
    assert context["progress"]["status"] == "invalid"
    assert context["progress"]["evidence_id"] == latest["evidence_id"]
    assert "progress_orientation" in context["required_sections"]
    assert "Latest progress receipt is invalid" in context["markdown"]


@pytest.mark.parametrize(
    ("tamper_sql", "expected_health"),
    [
        (
            "UPDATE events SET event_type = 'tampered_progress' "
            "WHERE event_type = 'progress_receipt_recorded' "
            "AND json_extract(payload_json, '$.evidence_id') = ?",
            "anchor_missing",
        ),
        (
            "UPDATE evidence SET type = 'adhoc_artifact' WHERE id = ?",
            "wrong_evidence_type",
        ),
    ],
)
def test_unanchored_or_wrong_type_latest_progress_never_falls_back(
    tmp_path: Path,
    capsys,
    tamper_sql: str,
    expected_health: str,
) -> None:
    root = tmp_path / "project"
    _init_git_project(root, capsys)
    older = _record_progress(root, capsys, milestone="Older valid milestone")
    latest = _record_progress(root, capsys, milestone="Newest tampered milestone")

    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute(tamper_sql, (latest["evidence_id"],))
        conn.commit()
    finally:
        conn.close()

    assert main([
        "--root", str(root), "resume", "--target", "T-0001", "--json",
    ]) == 0
    handoff = _json(capsys)["handoff_packet"]
    assert handoff["progress"]["status"] == "invalid"
    assert handoff["progress"]["evidence_id"] == latest["evidence_id"]
    assert handoff["progress"]["artifact_health"] == expected_health
    assert f"evidence:{older['evidence_id']}" not in {
        item["ref"]
        for item in handoff["context_refs"]
        if item["kind"] == "progress-receipt/v1"
    }
