from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import pcl.lifecycle_repair as lifecycle_repair
from pcl.cli import main
from pcl.contracts.completion_packet import with_computed_packet_id
from pcl.db import connect
from pcl.lifecycle_repair import LifecycleRepairAction, LifecycleRepairPlanError
from pcl.relationship_repair import RelationshipRepairError, apply_structural_actions
from pcl.validators import _done_feature_lifecycle_findings


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "lifecycle_repair"


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _init(root: Path, capsys) -> None:
    assert main(["init", "--target", str(root)]) == 0
    capsys.readouterr()
    assert main(["--root", str(root), "migrate"]) == 0
    capsys.readouterr()


def _add_feature_story_test(root: Path, capsys, *, name: str) -> tuple[str, str, str]:
    assert main([
        "--root", str(root), "feature", "add", "--name", name, "--surface", "cli:pcl",
    ]) == 0
    feature_id = capsys.readouterr().out.strip()
    assert main([
        "--root", str(root), "story", "draft", "--feature", feature_id,
        "--actor", "operator", "--goal", "repair legacy lifecycle state",
        "--expected-behavior", "the planner preserves operator choice",
    ]) == 0
    story_id = capsys.readouterr().out.strip()
    assert main([
        "--root", str(root), "story", "approve", story_id, "--summary", "reviewed",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(root), "test", "plan", "--feature", feature_id,
        "--story", story_id, "--type", "acceptance", "--scenario", "legacy state",
        "--expected", "a deterministic read-only repair plan",
    ]) == 0
    test_id = capsys.readouterr().out.strip()
    return feature_id, story_id, test_id


def _add_evidence(root: Path, capsys, *, filename: str) -> str:
    (root / filename).write_text(f"{filename}: passed\n", encoding="utf-8")
    assert main([
        "--root", str(root), "evidence", "add", "--file", filename,
        "--summary", f"Acceptance output for {filename}", "--copy", "--json",
    ]) == 0
    return str(_json(capsys)["evidence"]["id"])


def _existing_project_fixture(root: Path, capsys) -> None:
    _init(root, capsys)
    _, story_one, test_one = _add_feature_story_test(root, capsys, name="Repair one")
    evidence_one = _add_evidence(root, capsys, filename="one.txt")
    assert main([
        "--root", str(root), "test", "pass", test_one, "--summary", "passed",
        "--evidence-id", evidence_one,
    ]) == 0
    capsys.readouterr()

    _, _, test_two = _add_feature_story_test(root, capsys, name="Repair two")
    evidence_two = _add_evidence(root, capsys, filename="two.txt")
    assert main([
        "--root", str(root), "test", "pass", test_two, "--summary", "passed",
        "--evidence-id", evidence_two,
    ]) == 0
    capsys.readouterr()

    assert main(["--root", str(root), "goal", "create", "--title", "Legacy goal"]) == 0
    capsys.readouterr()

    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute("UPDATE test_cases SET story_id = NULL WHERE id = ?", (test_one,))
        conn.execute(
            "DELETE FROM evidence_links WHERE evidence_id = ? AND target_type = 'test_case' "
            "AND target_id = ? AND link_role = 'acceptance'",
            (evidence_one, test_one),
        )
        conn.execute(
            "DELETE FROM evidence_links WHERE evidence_id = ? AND target_type = 'test_case' "
            "AND target_id = ? AND link_role = 'acceptance'",
            (evidence_two, test_two),
        )
        conn.execute(
            "INSERT INTO evidence_links(evidence_id, target_type, target_id, link_role, created_at) "
            "VALUES (?, 'test_case', ?, 'acceptance', '2026-01-01T00:00:00Z')",
            (evidence_two, test_one),
        )
        conn.execute(
            "UPDATE goals SET status = 'closed', completion_json = ? WHERE id = 'G-0001'",
            (json.dumps({"closure": {"summary": "legacy inline closure"}}),),
        )
        conn.commit()
    finally:
        conn.close()

    assert story_one == "US-0001"
    assert test_one == "TC-0001"
    assert test_two == "TC-0002"
    assert evidence_one == "E-0001"
    assert evidence_two == "E-0002"


def _state_snapshot(root: Path) -> dict:
    files = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = connect(root / ".project-loop" / "project.db")
    try:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
            for table in ("events", "outbox_records", "evidence", "evidence_links")
        }
    finally:
        conn.close()
    return {"files": files, "counts": counts}


def _unordered_done_feature_fixture(root: Path, capsys) -> None:
    _init(root, capsys)
    assert main([
        "--root", str(root), "feature", "add", "--name", "Unordered children",
        "--surface", "cli:pcl",
    ]) == 0
    assert capsys.readouterr().out.strip() == "F-0001"
    for index in range(1, 4):
        assert main([
            "--root", str(root), "story", "draft", "--feature", "F-0001",
            "--actor", "operator", "--goal", f"review story {index}",
            "--expected-behavior", f"story {index} remains explicit",
        ]) == 0
        story_id = capsys.readouterr().out.strip()
        assert main([
            "--root", str(root), "test", "plan", "--feature", "F-0001",
            "--story", story_id, "--type", "acceptance",
            "--scenario", f"planned test {index}", "--expected", "operator review",
        ]) == 0
        capsys.readouterr()
        assert main([
            "--root", str(root), "defect", "open", "--feature", "F-0001",
            "--severity", "medium", "--expected", f"expected {index}",
            "--actual", f"actual {index}",
        ]) == 0
        capsys.readouterr()
    conn = connect(root / ".project-loop" / "project.db")
    try:
        conn.execute("UPDATE features SET status = 'done' WHERE id = 'F-0001'")
        conn.commit()
    finally:
        conn.close()


def test_classification_is_closed_public_enum() -> None:
    with pytest.raises(ValueError, match="classification"):
        LifecycleRepairAction(
            finding_code="future_finding",
            classification="automatic",
            action_kind="future_action",
            entity={"type": "", "id": ""},
            related=[],
            safe_to_apply=False,
            requires_human=True,
            command="pcl validate --strict --json",
            reason="Future behavior must not silently expand the public enum.",
        )


def test_plan_matches_all_classifications_fixture_and_is_deterministic(
    tmp_path: Path,
    capsys,
) -> None:
    _existing_project_fixture(tmp_path, capsys)
    expected = json.loads((FIXTURE_ROOT / "all_classifications_v1.json").read_text(encoding="utf-8"))

    before = _state_snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    first_output = capsys.readouterr()
    assert first_output.err == ""
    first = json.loads(first_output.out)
    middle = _state_snapshot(tmp_path)

    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--dry-run", "--json",
    ]) == 0
    second_output = capsys.readouterr()
    assert second_output.err == ""
    second = json.loads(second_output.out)
    after = _state_snapshot(tmp_path)

    assert first == expected
    assert second == expected
    assert first_output.out == second_output.out
    assert before == middle == after
    assert set(first["summary"]) == {"structural", "semantic", "human_review", "unsupported"}
    assert [action["action_id"] for action in first["actions"]] == [
        "LR-0001", "LR-0002", "LR-0003", "LR-0004",
    ]
    assert [action["sort_key"] for action in first["actions"]] == sorted(
        action["sort_key"] for action in first["actions"]
    )
    assert first["actions"][1]["action_kind"] == "inspect_story_candidate"
    assert first["actions"][1]["related"] == [{"type": "user_story", "id": "US-0001"}]
    assert first["actions"][1]["safe_to_apply"] is False
    assert first["actions"][1]["requires_human"] is True


def test_text_output_uses_json_order_classes_and_concrete_ids(tmp_path: Path, capsys) -> None:
    _existing_project_fixture(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    plan = _json(capsys)
    assert main(["--root", str(tmp_path), "repair", "lifecycle"]) == 0
    text = capsys.readouterr()
    assert text.err == ""

    positions = []
    for action in plan["actions"]:
        line = (
            f"[{action['classification'].upper()}] {action['action_id']} "
            f"{action['action_kind']} {action['entity']['type']}:{action['entity']['id']}"
        )
        assert line in text.out
        assert action["finding_code"] in text.out
        related_text = ", ".join(
            f"{related['type']}:{related['id']}" for related in action["related"]
        )
        assert f"  Related: {related_text or 'none'}" in text.out
        positions.append(text.out.index(line))
    assert positions == sorted(positions)
    for classification, count in plan["summary"].items():
        assert f"{classification}={count}" in text.out


def test_empty_project_has_zero_filled_summary(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    assert _json(capsys) == {
        "contract_version": "lifecycle-repair-plan/v1",
        "mode": "plan",
        "mutated": False,
        "summary": {
            "structural": 0,
            "semantic": 0,
            "human_review": 0,
            "unsupported": 0,
        },
        "actions": [],
    }


def test_exactly_one_or_multiple_story_candidates_remain_semantic(
    tmp_path: Path,
    capsys,
) -> None:
    _existing_project_fixture(tmp_path, capsys)

    assert main([
        "--root", str(tmp_path), "story", "draft", "--feature", "F-0001",
        "--actor", "operator", "--goal", "consider another meaning",
        "--expected-behavior", "candidate count does not choose semantics",
    ]) == 0
    assert capsys.readouterr().out.strip() == "US-0003"
    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    plan = _json(capsys)

    action = next(item for item in plan["actions"] if item["finding_code"] == "test_story_required")
    assert action["classification"] == "semantic"
    assert action["action_kind"] == "choose_story_relationship"
    assert action["related"] == [
        {"type": "user_story", "id": "US-0001"},
        {"type": "user_story", "id": "US-0003"},
    ]
    assert action["safe_to_apply"] is False
    assert action["requires_human"] is True

    assert main(["--root", str(tmp_path), "repair", "lifecycle"]) == 0
    text = capsys.readouterr().out
    assert "Related: user_story:US-0001, user_story:US-0003" in text


def test_reverse_unordered_selects_preserves_plan_bytes_related_and_legacy_messages(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    _unordered_done_feature_fixture(tmp_path, capsys)

    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    normal_bytes = capsys.readouterr().out.encode("utf-8")
    normal_plan = json.loads(normal_bytes)

    original_connect = lifecycle_repair._connect_read_only

    def reverse_connect(db_path: Path):
        conn = original_connect(db_path)
        conn.execute("PRAGMA reverse_unordered_selects = ON")
        return conn

    monkeypatch.setattr(lifecycle_repair, "_connect_read_only", reverse_connect)
    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    reversed_bytes = capsys.readouterr().out.encode("utf-8")
    reversed_plan = json.loads(reversed_bytes)

    assert reversed_bytes == normal_bytes
    assert reversed_plan == normal_plan
    related_by_kind = {
        action["action_kind"]: action["related"] for action in normal_plan["actions"]
    }
    assert related_by_kind["inspect_feature_stories"] == [
        {"type": "user_story", "id": "US-0001"},
        {"type": "user_story", "id": "US-0002"},
        {"type": "user_story", "id": "US-0003"},
    ]
    assert related_by_kind["inspect_feature_tests"] == [
        {"type": "test_case", "id": "TC-0001"},
        {"type": "test_case", "id": "TC-0002"},
        {"type": "test_case", "id": "TC-0003"},
    ]
    assert related_by_kind["review_open_feature_defects"] == [
        {"type": "defect", "id": "D-0001"},
        {"type": "defect", "id": "D-0002"},
        {"type": "defect", "id": "D-0003"},
    ]

    normal_conn = connect(tmp_path / ".project-loop" / "project.db")
    reverse_conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        reverse_conn.execute("PRAGMA reverse_unordered_selects = ON")
        normal_findings = _done_feature_lifecycle_findings(normal_conn)
        reverse_findings = _done_feature_lifecycle_findings(reverse_conn)
    finally:
        normal_conn.close()
        reverse_conn.close()
    assert [finding.message for finding in reverse_findings] == [
        finding.message for finding in normal_findings
    ]
    assert normal_findings[0].message.endswith(
        "incomplete Stories: US-0001,US-0002,US-0003."
    )


def test_drifted_and_wrong_role_evidence_are_unsupported(tmp_path: Path, capsys) -> None:
    _existing_project_fixture(tmp_path, capsys)
    copied = (
        tmp_path
        / ".project-loop"
        / "evidence"
        / "adhoc-files"
        / "e-0001"
        / "01-one.txt"
    )
    copied.write_text("drifted\n", encoding="utf-8")
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE evidence_links SET target_id = 'TC-0002', link_role = 'supporting' "
            "WHERE evidence_id = 'E-0002'"
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    plan = _json(capsys)
    evidence_actions = {
        action["entity"]["id"]: action
        for action in plan["actions"]
        if action["finding_code"] == "test_acceptance_evidence_required"
    }
    assert evidence_actions["TC-0001"]["classification"] == "unsupported"
    assert evidence_actions["TC-0001"]["action_kind"] == "report_invalid_test_evidence"
    assert evidence_actions["TC-0002"]["classification"] == "unsupported"
    assert evidence_actions["TC-0002"]["action_kind"] == "report_conflicting_evidence_link"


def test_valid_same_goal_packet_with_only_missing_link_is_structural(
    tmp_path: Path,
    capsys,
) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Packet goal"]) == 0
    capsys.readouterr()
    packet = json.loads(
        Path("tests/fixtures/completion_packet/full.json").read_text(encoding="utf-8")
    )
    packet["target"] = {
        "type": "goal",
        "id": "G-0001",
        "intent": "Repair only the missing completion packet link",
        "work_brief_ref": "evidence:E-0001",
    }
    packet = with_computed_packet_id(packet)
    packet_path = tmp_path / "goal-packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "INSERT INTO evidence(id, type, path, command, summary, created_at) "
            "VALUES ('E-0001', 'completion_packet', 'goal-packet.json', NULL, 'packet', "
            "'2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "UPDATE goals SET status = 'closed', completion_json = ? WHERE id = 'G-0001'",
            (
                json.dumps(
                    {
                        "closure": {
                            "summary": "legacy packet closure",
                            "evidence_id": "E-0001",
                            "proof_type": "completion_packet",
                        }
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    before = _state_snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    plan = _json(capsys)
    after = _state_snapshot(tmp_path)

    assert plan["summary"] == {
        "structural": 1,
        "semantic": 0,
        "human_review": 0,
        "unsupported": 0,
    }
    assert plan["actions"][0]["action_kind"] == "add_missing_completion_packet_link"
    assert plan["actions"][0]["safe_to_apply"] is True
    assert plan["actions"][0]["requires_human"] is False
    assert before == after

    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--apply-structural", "--json"
    ]) == 0
    applied = _json(capsys)
    assert applied["changed"] is True
    assert applied["relationships"] == [{
        "after": True, "before": False, "evidence_id": "E-0001",
        "role": "completion_packet", "target_id": "G-0001", "target_type": "goal",
    }]


def test_completion_packet_link_rejects_valid_packet_for_different_target(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    for title in ("Packet goal", "Other goal"):
        assert main(["--root", str(tmp_path), "goal", "create", "--title", title]) == 0
        capsys.readouterr()
    packet = json.loads(Path("tests/fixtures/completion_packet/full.json").read_text(encoding="utf-8"))
    packet["target"] = {
        "type": "goal", "id": "G-0001", "intent": "Bound elsewhere",
        "work_brief_ref": "evidence:E-0001",
    }
    (tmp_path / "packet.json").write_text(
        json.dumps(with_computed_packet_id(packet)), encoding="utf-8"
    )
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "INSERT INTO evidence(id, type, path, summary, created_at) VALUES "
            "('E-0001', 'completion_packet', 'packet.json', 'packet', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()
    before = _state_snapshot(tmp_path)
    assert main([
        "--root", str(tmp_path), "evidence", "link", "E-0001",
        "--target", "goal:G-0002", "--role", "completion_packet",
        "--summary", "Must reject mismatch", "--json",
    ]) == 2
    assert _json(capsys)["error"]["code"] == "evidence_link_packet_target_mismatch"
    assert _state_snapshot(tmp_path) == before


def test_invalid_goal_verification_reference_is_unsupported(tmp_path: Path, capsys) -> None:
    _init(tmp_path, capsys)
    assert main(["--root", str(tmp_path), "goal", "create", "--title", "Legacy goal"]) == 0
    capsys.readouterr()
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "UPDATE goals SET status = 'closed', completion_json = ? WHERE id = 'G-0001'",
            (
                json.dumps(
                    {
                        "closure": {
                            "summary": "legacy verification",
                            "verification_id": "V-9999",
                        }
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert main(["--root", str(tmp_path), "repair", "lifecycle", "--json"]) == 0
    action = _json(capsys)["actions"][0]
    assert action["classification"] == "unsupported"
    assert action["action_kind"] == "report_invalid_goal_verification"
    assert action["related"] == [{"type": "verification", "id": "V-9999"}]
    assert action["command"] == "pcl verification read V-9999 --json"


def test_repair_lifecycle_rejects_legacy_apply_mode() -> None:
    assert main(["repair", "lifecycle", "--apply", "--json"]) == 2


def test_test_link_repairs_story_and_evidence_once_in_one_event(tmp_path: Path, capsys) -> None:
    _existing_project_fixture(tmp_path, capsys)
    before = _state_snapshot(tmp_path)

    assert main([
        "--root", str(tmp_path), "test", "link", "TC-0001",
        "--story", "US-0001", "--evidence-id", "E-0001",
        "--summary", "Restore reviewed terminal relationships", "--json",
    ]) == 0
    repaired = _json(capsys)
    assert repaired["changed"] is True
    assert repaired["before"] == {"story_id": None, "evidence_id": "E-0001"}
    assert repaired["after"] == {"story_id": "US-0001", "evidence_id": "E-0001"}
    assert repaired["event_id"].startswith("EV-")

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        test = dict(conn.execute(
            "SELECT story_id, evidence_id, status, created_at FROM test_cases WHERE id = 'TC-0001'"
        ).fetchone())
        event = dict(conn.execute(
            "SELECT event_type, payload_json FROM events WHERE id = ?", (repaired["event_id"],)
        ).fetchone())
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_links WHERE evidence_id = 'E-0001' "
            "AND target_type = 'test_case' AND target_id = 'TC-0001' AND link_role = 'acceptance'"
        ).fetchone()["n"] == 1
    finally:
        conn.close()
    assert test["status"] == "passing"
    assert event["event_type"] == "test_links_repaired"
    assert json.loads(event["payload_json"])["summary"] == "Restore reviewed terminal relationships"
    assert _state_snapshot(tmp_path)["counts"]["events"] == before["counts"]["events"] + 1
    assert _state_snapshot(tmp_path)["counts"]["outbox_records"] == before["counts"]["outbox_records"] + 1

    stable = _state_snapshot(tmp_path)
    assert main([
        "--root", str(tmp_path), "test", "link", "TC-0001",
        "--story", "US-0001", "--evidence-id", "E-0001",
        "--summary", "Exact retry", "--json",
    ]) == 0
    assert _json(capsys)["changed"] is False
    assert _state_snapshot(tmp_path) == stable


def test_test_link_combined_failure_is_zero_mutation(tmp_path: Path, capsys) -> None:
    _existing_project_fixture(tmp_path, capsys)
    before = _state_snapshot(tmp_path)
    assert main([
        "--root", str(tmp_path), "test", "link", "TC-0001",
        "--story", "US-0001", "--evidence-id", "E-9999",
        "--summary", "Must remain atomic", "--json",
    ]) == 2
    error = _json(capsys)
    assert error["error"]["code"] == "test_link_invalid_evidence"
    assert _state_snapshot(tmp_path) == before


def test_structural_apply_repairs_current_safe_actions_atomically(tmp_path: Path, capsys) -> None:
    _existing_project_fixture(tmp_path, capsys)
    before = _state_snapshot(tmp_path)
    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--apply-structural", "--json"
    ]) == 0
    result = _json(capsys)
    assert result["mode"] == "apply_structural"
    assert result["changed"] is True
    assert result["applied_action_ids"] == ["LR-0001"]
    assert result["relationships"] == [{
        "after": True, "before": False, "evidence_id": "E-0001", "role": "acceptance",
        "target_id": "TC-0001", "target_type": "test_case",
    }]
    after = _state_snapshot(tmp_path)
    assert after["counts"]["evidence_links"] == before["counts"]["evidence_links"] + 1
    assert after["counts"]["events"] == before["counts"]["events"] + 1
    assert after["counts"]["outbox_records"] == before["counts"]["outbox_records"] + 1

    assert main([
        "--root", str(tmp_path), "repair", "lifecycle", "--apply-structural", "--json"
    ]) == 0
    rerun = _json(capsys)
    assert rerun["changed"] is False
    assert _state_snapshot(tmp_path) == after


def test_evidence_link_repairs_only_matching_terminal_test_pointer(tmp_path: Path, capsys) -> None:
    _existing_project_fixture(tmp_path, capsys)
    before = _state_snapshot(tmp_path)
    assert main([
        "--root", str(tmp_path), "evidence", "link", "E-0001",
        "--target", "test_case:TC-0001", "--role", "acceptance",
        "--summary", "Restore missing routing row", "--json",
    ]) == 0
    linked = _json(capsys)
    assert linked["changed"] is True
    assert linked["event_id"].startswith("EV-")
    after = _state_snapshot(tmp_path)
    assert after["counts"]["evidence_links"] == before["counts"]["evidence_links"] + 1
    assert after["counts"]["events"] == before["counts"]["events"] + 1

    assert main([
        "--root", str(tmp_path), "evidence", "link", "E-0001",
        "--target", "test_case:TC-0001", "--role", "acceptance",
        "--summary", "Exact retry", "--json",
    ]) == 0
    assert _json(capsys)["changed"] is False
    assert _state_snapshot(tmp_path) == after

    rejected_before = _state_snapshot(tmp_path)
    assert main([
        "--root", str(tmp_path), "evidence", "link", "E-0001",
        "--target", "test_case:TC-0002", "--role", "acceptance",
        "--summary", "Must direct to test link", "--json",
    ]) == 2
    assert _json(capsys)["error"]["code"] == "evidence_link_test_pointer_mismatch"
    assert _state_snapshot(tmp_path) == rejected_before


def test_test_link_story_change_with_existing_acceptance_link_does_not_reinsert(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    feature, _, test_id = _add_feature_story_test(tmp_path, capsys, name="Existing link")
    evidence_id = _add_evidence(tmp_path, capsys, filename="existing.txt")
    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "passed", "--evidence-id", evidence_id,
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "story", "draft", "--feature", feature,
        "--actor", "operator", "--goal", "choose replacement",
        "--expected-behavior", "existing Evidence link remains unique",
    ]) == 0
    replacement_story = capsys.readouterr().out.strip()
    assert main([
        "--root", str(tmp_path), "story", "approve", replacement_story,
        "--summary", "reviewed",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "test", "link", test_id,
        "--story", replacement_story, "--evidence-id", evidence_id,
        "--summary", "Change Story only", "--json",
    ]) == 0
    assert _json(capsys)["changed"] is True
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_links WHERE evidence_id = ? "
            "AND target_type = 'test_case' AND target_id = ? AND link_role = 'acceptance'",
            (evidence_id, test_id),
        ).fetchone()["n"] == 1
    finally:
        conn.close()


def test_test_link_pointer_replacement_preserves_old_evidence_and_link(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    _, _, test_id = _add_feature_story_test(tmp_path, capsys, name="History")
    old_id = _add_evidence(tmp_path, capsys, filename="old.txt")
    new_id = _add_evidence(tmp_path, capsys, filename="new.txt")
    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "old proof", "--evidence-id", old_id,
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(tmp_path), "test", "link", test_id,
        "--evidence-id", new_id, "--summary", "Reviewed replacement", "--json",
    ]) == 0
    assert _json(capsys)["after"]["evidence_id"] == new_id
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM evidence WHERE id IN (?, ?)", (old_id, new_id)).fetchone()["n"] == 2
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_links WHERE evidence_id = ? AND "
            "target_type = 'test_case' AND target_id = ? AND link_role = 'acceptance'",
            (old_id, test_id),
        ).fetchone()["n"] == 1
    finally:
        conn.close()


def test_structural_apply_unknown_and_stale_batches_are_zero_mutation(
    tmp_path: Path, capsys
) -> None:
    _existing_project_fixture(tmp_path, capsys)
    base = {
        "action_id": "LR-0001", "classification": "structural", "safe_to_apply": True,
        "action_kind": "add_missing_evidence_link",
        "entity": {"type": "test_case", "id": "TC-0001"},
        "related": [{"type": "evidence", "id": "E-0001"}],
    }
    before = _state_snapshot(tmp_path)
    with pytest.raises(LifecycleRepairPlanError) as unknown:
        apply_structural_actions(tmp_path_paths(tmp_path), [{**base, "action_kind": "future_action"}])
    assert unknown.value.code == "repair_unknown_action_kind"
    assert _state_snapshot(tmp_path) == before

    duplicate = {**base, "action_id": "LR-0002"}
    with pytest.raises(RelationshipRepairError) as stale:
        apply_structural_actions(tmp_path_paths(tmp_path), [base, duplicate])
    assert stale.value.code == "repair_stale_precondition"
    assert _state_snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"classification": "future"}, "repair_unknown_classification"),
        ({"classification": "semantic"}, "repair_action_classification_mismatch"),
        (
            {
                "classification": "semantic",
                "action_kind": "inspect_story_candidate",
                "safe_to_apply": True,
            },
            "repair_non_structural_safe_action",
        ),
    ],
)
def test_structural_apply_rejects_malformed_plan_actions_without_mutation(
    tmp_path: Path, capsys, patch: dict, code: str
) -> None:
    _existing_project_fixture(tmp_path, capsys)
    action = {
        "action_id": "LR-0001",
        "classification": "structural",
        "safe_to_apply": True,
        "action_kind": "add_missing_evidence_link",
        "entity": {"type": "test_case", "id": "TC-0001"},
        "related": [{"type": "evidence", "id": "E-0001"}],
        **patch,
    }
    before = _state_snapshot(tmp_path)
    with pytest.raises(LifecycleRepairPlanError) as error:
        apply_structural_actions(tmp_path_paths(tmp_path), [action])
    assert error.value.code == code
    assert _state_snapshot(tmp_path) == before


def test_structural_apply_accepts_known_non_structural_safe_false_action(
    tmp_path: Path, capsys
) -> None:
    _existing_project_fixture(tmp_path, capsys)
    before = _state_snapshot(tmp_path)
    result = apply_structural_actions(
        tmp_path_paths(tmp_path),
        [{
            "action_id": "LR-0001",
            "classification": "semantic",
            "safe_to_apply": False,
            "action_kind": "inspect_story_candidate",
            "entity": {"type": "test_case", "id": "TC-0001"},
            "related": [{"type": "user_story", "id": "US-0001"}],
        }],
    )
    assert result["changed"] is False
    assert _state_snapshot(tmp_path) == before


def test_evidence_link_role_contracts_are_public_and_zero_mutation(
    tmp_path: Path, capsys
) -> None:
    _init(tmp_path, capsys)
    feature, _, _ = _add_feature_story_test(tmp_path, capsys, name="Role contract")
    healthy = _add_evidence(tmp_path, capsys, filename="feature.txt")
    assert main([
        "--root", str(tmp_path), "evidence", "link", healthy,
        "--target", f"feature:{feature}", "--role", "acceptance",
        "--summary", "Healthy Feature acceptance", "--json",
    ]) == 0
    assert _json(capsys)["changed"] is True

    assert main([
        "--root", str(tmp_path), "task", "create", "--title", "Receipt target",
    ]) == 0
    capsys.readouterr()
    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        conn.execute(
            "INSERT INTO evidence(id, type, path, summary, created_at) VALUES "
            "('E-9999', 'manual_note', 'inline:note', 'wrong type', "
            "'2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()

    cases = [
        ("E-9999", f"feature:{feature}", "acceptance", "evidence_link_invalid_acceptance"),
        (healthy, "task:T-0001", "code_context", "evidence_link_reserved_role"),
        (healthy, "task:T-0001", "verification_check", "evidence_link_reserved_role"),
        (healthy, "task:T-0001", "completion_check", "evidence_link_incompatible_role"),
    ]
    for evidence_id, target, role, code in cases:
        before = _state_snapshot(tmp_path)
        assert main([
            "--root", str(tmp_path), "evidence", "link", evidence_id,
            "--target", target, "--role", role, "--summary", "Reject unsafe generic link",
            "--json",
        ]) == 2
        assert _json(capsys)["error"]["code"] == code
        assert _state_snapshot(tmp_path) == before


def tmp_path_paths(root: Path):
    from pcl.paths import resolve_paths

    return resolve_paths(root)
