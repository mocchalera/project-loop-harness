from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.db import connect


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()
    assert main(["--root", str(root), "migrate"]) == 0
    capsys.readouterr()


def _counts(root: Path) -> tuple[int, int, int, bytes]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return (
            int(conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]),
            int(conn.execute("SELECT COUNT(*) AS n FROM outbox_records").fetchone()["n"]),
            int(conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]),
            (root / ".project-loop" / "events.jsonl").read_bytes(),
        )
    finally:
        conn.close()


def _feature_story_test(root: Path, capsys, *, approve: bool = True) -> tuple[str, str, str]:
    assert (
        main(["--root", str(root), "feature", "add", "--name", "Integrity", "--surface", "cli:pcl"])
        == 0
    )
    feature_id = capsys.readouterr().out.strip()
    assert (
        main(
            [
                "--root",
                str(root),
                "story",
                "draft",
                "--feature",
                feature_id,
                "--actor",
                "agent",
                "--goal",
                "prove completion",
                "--expected-behavior",
                "terminal state is evidence-backed",
            ]
        )
        == 0
    )
    story_id = capsys.readouterr().out.strip()
    if approve:
        assert (
            main(["--root", str(root), "story", "approve", story_id, "--summary", "reviewed"]) == 0
        )
        capsys.readouterr()
    assert (
        main(
            [
                "--root",
                str(root),
                "test",
                "plan",
                "--feature",
                feature_id,
                "--story",
                story_id,
                "--type",
                "acceptance",
                "--scenario",
                "integrity gate",
                "--expected",
                "guarded",
            ]
        )
        == 0
    )
    test_id = capsys.readouterr().out.strip()
    return feature_id, story_id, test_id


def _adhoc_evidence(root: Path, capsys, text: str = "passed\n") -> str:
    artifact = root / "result.txt"
    artifact.write_text(text, encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(root),
                "evidence",
                "add",
                "--file",
                "result.txt",
                "--summary",
                "acceptance output",
                "--copy",
                "--json",
            ]
        )
        == 0
    )
    return str(_json(capsys)["evidence"]["id"])


def test_terminal_evidence_id_direct_route_and_links(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    feature_id, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_id = _adhoc_evidence(tmp_path, capsys)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "pass",
                test_id,
                "--summary",
                "passed",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 0
    )
    passed = _json(capsys)
    assert passed["evidence_id"] == evidence_id
    assert passed["evidence_mode"] == "id"

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "feature",
                "status",
                feature_id,
                "--status",
                "done",
                "--summary",
                "complete",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 0
    )
    done = _json(capsys)
    assert done["evidence_id"] == evidence_id
    assert done["evidence_mode"] == "id"

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        links = {
            (row["target_type"], row["target_id"], row["link_role"])
            for row in conn.execute(
                "SELECT target_type, target_id, link_role FROM evidence_links WHERE evidence_id = ?",
                (evidence_id,),
            )
        }
    finally:
        conn.close()
    assert ("test_case", test_id, "acceptance") in links
    assert ("feature", feature_id, "acceptance") in links


def test_test_pass_guards_are_typed_and_zero_mutation(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _, _, test_id = _feature_story_test(tmp_path, capsys, approve=False)
    evidence_id = _adhoc_evidence(tmp_path, capsys)
    before = _counts(tmp_path)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "pass",
                test_id,
                "--summary",
                "passed",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 2
    )
    error = _json(capsys)
    assert error["error"]["code"] == "test_story_not_terminal"
    assert _counts(tmp_path) == before


def test_test_pass_without_story_rejects_with_zero_mutation(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    config = tmp_path / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "lifecycle_integrity: enforced",
            "lifecycle_integrity: advisory",
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "feature",
                "add",
                "--name",
                "Unlinked",
                "--surface",
                "cli:pcl",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "plan",
                "--feature",
                "F-0001",
                "--type",
                "acceptance",
                "--scenario",
                "unlinked",
                "--expected",
                "reject",
            ]
        )
        == 0
    )
    capsys.readouterr()
    evidence_id = _adhoc_evidence(tmp_path, capsys)
    before = _counts(tmp_path)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "pass",
                "TC-0001",
                "--summary",
                "passed",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 2
    )
    assert _json(capsys)["error"]["code"] == "test_story_required"
    assert _counts(tmp_path) == before


def test_drifted_evidence_is_rejected_before_mutation(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_id = _adhoc_evidence(tmp_path, capsys)
    (
        tmp_path
        / ".project-loop"
        / "evidence"
        / "adhoc-files"
        / evidence_id.lower()
        / "01-result.txt"
    ).write_text("changed\n", encoding="utf-8")
    before = _counts(tmp_path)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "pass",
                test_id,
                "--summary",
                "passed",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 2
    )
    assert _json(capsys)["error"]["code"] == "test_acceptance_evidence_required"
    assert _counts(tmp_path) == before


def test_no_evidence_test_transition_has_no_legacy_warning_or_mode(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "block",
                test_id,
                "--summary",
                "blocked",
                "--json",
            ]
        )
        == 0
    )
    payload = _json(capsys)
    assert "warnings" not in payload
    assert "evidence_mode" not in payload
    events = [
        json.loads(line)
        for line in (tmp_path / ".project-loop" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event = next(item for item in reversed(events) if item["event_type"] == "test_case_blocked")
    assert "evidence_mode" not in event["payload"]


def test_feature_done_guard_rejects_incomplete_lifecycle_without_mutation(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    feature_id, _, _ = _feature_story_test(tmp_path, capsys, approve=False)
    evidence_id = _adhoc_evidence(tmp_path, capsys)
    before = _counts(tmp_path)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "feature",
                "status",
                feature_id,
                "--status",
                "done",
                "--summary",
                "complete",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 2
    )
    assert _json(capsys)["error"]["code"] == "feature_done_story_incomplete"
    assert _counts(tmp_path) == before


def test_lifecycle_validation_is_advisory_without_policy_and_enforced_with_policy(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    config = tmp_path / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "\nvalidation:\n  lifecycle_integrity: enforced\n", "\n"
        ),
        encoding="utf-8",
    )
    feature_id, story_id, test_id = _feature_story_test(tmp_path, capsys)
    evidence_id = _adhoc_evidence(tmp_path, capsys)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "pass",
                test_id,
                "--summary",
                "passed",
                "--evidence-id",
                evidence_id,
            ]
        )
        == 0
    )
    capsys.readouterr()
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("UPDATE features SET status = 'done' WHERE id = ?", (feature_id,))
        conn.execute("UPDATE user_stories SET status = 'draft' WHERE id = ?", (story_id,))
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    advisory = _json(capsys)
    assert any("test_story_not_terminal" in item for item in advisory["warnings"])
    assert any("feature_done_story_incomplete" in item for item in advisory["warnings"])
    advisory_findings = {item["code"]: item for item in advisory["findings"]}
    assert advisory_findings["test_story_not_terminal"]["severity"] == "warning"
    assert advisory_findings["feature_done_story_incomplete"] == {
        "code": "feature_done_story_incomplete",
        "severity": "warning",
        "message": next(
            item for item in advisory["warnings"] if "feature_done_story_incomplete" in item
        ),
        "entity": {"type": "feature", "id": feature_id},
        "related": [{"type": "user_story", "id": story_id, "status": "draft"}],
        "repair_class": "semantic",
        "requires_human": True,
        "suggested_commands": [
            f"pcl --json story read {story_id}",
            "pcl --json repair lifecycle --dry-run",
        ],
        "proof_scope": "historical",
    }

    with config.open("a", encoding="utf-8") as handle:
        handle.write("\nvalidation:\n  lifecycle_integrity: enforced\n")
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    enforced = _json(capsys)
    assert any("test_story_not_terminal" in item for item in enforced["errors"])
    assert any("feature_done_story_incomplete" in item for item in enforced["errors"])
    assert story_id in " ".join(enforced["errors"])
    enforced_findings = {item["code"]: item for item in enforced["findings"]}
    assert enforced_findings["feature_done_story_incomplete"]["severity"] == "error"
    assert (
        enforced_findings["feature_done_story_incomplete"]["entity"]
        == advisory_findings["feature_done_story_incomplete"]["entity"]
    )


def test_existing_passing_unlinked_test_is_advisory_then_enforced(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    config = tmp_path / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "\nvalidation:\n  lifecycle_integrity: enforced\n", "\n"
        ),
        encoding="utf-8",
    )
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_id = _adhoc_evidence(tmp_path, capsys)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "test",
                "pass",
                test_id,
                "--summary",
                "passed",
                "--evidence-id",
                evidence_id,
            ]
        )
        == 0
    )
    capsys.readouterr()
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute("UPDATE test_cases SET story_id = NULL WHERE id = ?", (test_id,))
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    advisory = _json(capsys)
    assert any("test_story_required" in item for item in advisory["warnings"])
    with config.open("a", encoding="utf-8") as handle:
        handle.write("\nvalidation:\n  lifecycle_integrity: enforced\n")
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    assert any("test_story_required" in item for item in _json(capsys)["errors"])


def test_legacy_raw_goal_closure_is_reported_and_new_raw_close_rejects(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    config = tmp_path / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "\nvalidation:\n  lifecycle_integrity: enforced\n", "\n"
        ),
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Legacy"]) == 0
    capsys.readouterr()
    before = _counts(tmp_path)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "goal",
                "close",
                "G-0001",
                "--summary",
                "raw",
                "--evidence",
                "reports/result.md",
                "--json",
            ]
        )
        == 2
    )
    assert _json(capsys)["error"]["code"] == "goal_close_verification_required"
    assert _counts(tmp_path) == before

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE goals SET status = 'closed', completion_json = ? WHERE id = 'G-0001'",
            (
                json.dumps(
                    {
                        "closure": {
                            "summary": "legacy",
                            "evidence": "reports/result.md",
                            "verification_id": None,
                        }
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert any("goal_close_verification_required" in item for item in _json(capsys)["warnings"])
    with config.open("a", encoding="utf-8") as handle:
        handle.write("\nvalidation:\n  lifecycle_integrity: enforced\n")
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 1
    assert any("goal_close_verification_required" in item for item in _json(capsys)["errors"])


def test_goal_close_accepts_same_target_completed_packet_and_rejects_cross_target(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "First"]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Second"]) == 0
    capsys.readouterr()
    packet = _completion_packet(tmp_path, goal_id="G-0001", outcome="COMPLETED_VERIFIED")
    evidence_id = _insert_packet_evidence(tmp_path, packet, goal_id="G-0001")

    before = _counts(tmp_path)
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "goal",
                "close",
                "G-0002",
                "--summary",
                "done",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 2
    )
    assert _json(capsys)["error"]["code"] == "goal_close_verification_required"
    assert _counts(tmp_path) == before

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "goal",
                "close",
                "G-0001",
                "--summary",
                "done",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 0
    )
    closed = _json(capsys)
    assert closed["proof_type"] == "completion_packet"
    assert closed["packet_outcome"] == "COMPLETED_VERIFIED"
    assert main(["--root", str(tmp_path), "report", "goal", "G-0001", "--json"]) == 0
    report = _json(capsys)["report"]
    assert report["closure_proof"] == {
        "proof_type": "completion_packet",
        "evidence_id": evidence_id,
        "verification_id": None,
        "packet_outcome": "COMPLETED_VERIFIED",
    }
    assert main(["--root", str(tmp_path), "render"]) == 0
    capsys.readouterr()
    dashboard = json.loads(
        (tmp_path / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
    goal = next(item for item in dashboard["goals"] if item["id"] == "G-0001")
    assert goal["closure_proof"]["evidence_id"] == evidence_id


def test_completed_packet_cannot_close_goal_with_incomplete_start_task(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "start", "Integrity follow-up", "--json"]) == 0
    started = _json(capsys)
    assert started["result"]["created_ids"]["goal"] == "G-0001"
    assert started["result"]["created_ids"]["task"] == "T-0001"
    packet = _completion_packet(tmp_path, goal_id="G-0001", outcome="COMPLETED_VERIFIED")
    evidence_id = _insert_packet_evidence(tmp_path, packet, goal_id="G-0001")
    before_counts = _counts(tmp_path)
    before_rows = _goal_and_task_rows(tmp_path)

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "goal",
                "close",
                "G-0001",
                "--summary",
                "packet complete",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 2
    )
    error = _json(capsys)["error"]
    assert error["code"] == "goal_close_tasks_incomplete"
    assert error["details"] == {
        "goal_id": "G-0001",
        "incomplete_tasks": [{"id": "T-0001", "status": "todo"}],
    }
    assert _counts(tmp_path) == before_counts
    assert _goal_and_task_rows(tmp_path) == before_rows

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "task",
                "status",
                "T-0001",
                "done",
                "--reason",
                "Implementation and acceptance checks completed",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "goal",
                "close",
                "G-0001",
                "--summary",
                "packet complete",
                "--evidence-id",
                evidence_id,
                "--json",
            ]
        )
        == 0
    )
    closed = _json(capsys)
    assert closed["status"] == "closed"
    assert closed["proof_type"] == "completion_packet"
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json(capsys)["ok"] is True


def _goal_and_task_rows(root: Path) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "goal": dict(
                conn.execute(
                    "SELECT status, completion_json, updated_at FROM goals WHERE id = 'G-0001'"
                ).fetchone()
            ),
            "task": dict(
                conn.execute("SELECT status, updated_at FROM tasks WHERE id = 'T-0001'").fetchone()
            ),
        }
    finally:
        conn.close()


def _completion_packet(root: Path, *, goal_id: str, outcome: str) -> dict:
    from pcl.contracts.completion_packet import with_computed_packet_id

    packet = {
        "contract_version": "completion-packet/v1",
        "producer": {"name": "project-loop-harness", "version": "0.4.1"},
        "generated_at": "2026-07-10T00:00:00Z",
        "outcome": outcome,
        "target": {
            "type": "goal",
            "id": goal_id,
            "intent": "Close direct goal",
            "work_brief_ref": None,
        },
        "repository": {
            "base_revision": "abc1234",
            "head_revision": "def5678",
            "diff_sha256": "sha256:" + "0" * 64,
            "dirty": False,
        },
        "changes": [{"path": "src/example.py", "change_type": "modified", "previous_path": None}],
        "checks": [],
        "claims": [],
        "unverified_claims": [],
        "risks": [],
        "human_decisions": [],
        "next_action": None,
    }
    return with_computed_packet_id(packet)


def _insert_packet_evidence(root: Path, packet: dict, *, goal_id: str) -> str:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        row = conn.execute(
            "SELECT MAX(CAST(SUBSTR(id, 3) AS INTEGER)) AS max_id FROM evidence WHERE id LIKE 'E-%'"
        ).fetchone()
        evidence_id = f"E-{int(row['max_id'] or 0) + 1:04d}"
        packet_path = (
            root
            / ".project-loop"
            / "evidence"
            / "completion-packets"
            / f"{evidence_id.lower()}-fixture.json"
        )
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        packet_path.write_text(json.dumps(packet, sort_keys=True) + "\n", encoding="utf-8")
        conn.execute(
            "INSERT INTO evidence(id, type, path, command, summary, created_at) VALUES (?, 'completion_packet', ?, 'pcl finish --emit-packet', 'fixture', '2026-07-10T00:00:00Z')",
            (evidence_id, str(packet_path.relative_to(root))),
        )
        conn.execute(
            "INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at) VALUES (?, 'goal', ?, 'completion_packet', '2026-07-10T00:00:00Z')",
            (evidence_id, goal_id),
        )
        conn.commit()
    finally:
        conn.close()
    return evidence_id
