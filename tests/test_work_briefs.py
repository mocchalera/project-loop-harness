from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from pcl.cli import main
from pcl.contracts.work_brief import (
    WORK_BRIEF_CONTRACT_VERSION,
    validate_work_brief,
    work_brief_schema,
)
from pcl.context import pack_context_for_task
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.resume import build_handoff_packet
from pcl.start import start_work


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "work_brief"


def _initialized_target(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "project"
    root.mkdir()
    paths = resolve_paths(root)
    init_project(paths)
    started = start_work(paths, intent="Implement a Work Brief contract")
    return root, str(started["result"]["created_ids"]["task"])


def _brief_for_target(tmp_path: Path, target_id: str, *, brief_id: str = "WB-0001") -> Path:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))
    value["brief_id"] = brief_id
    value["target"]["id"] = target_id
    path = tmp_path / f"{brief_id.lower()}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "evidence": int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "outbox": int(conn.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0]),
            "links": int(conn.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0]),
        }
    finally:
        conn.close()


def test_work_brief_schema_is_packaged_and_route_is_not_required() -> None:
    schema = work_brief_schema()

    assert schema["$id"].endswith("work-brief-v1.schema.json")
    assert "route" not in schema["required"]
    assert "status" not in schema["properties"]


def test_work_brief_validator_accepts_minimal_fixture() -> None:
    value = json.loads((FIXTURE_ROOT / "minimal.json").read_text(encoding="utf-8"))

    result = validate_work_brief(value)

    assert result.ok is True
    assert result.errors == ()


def test_contract_cli_validates_work_brief_without_state(capsys, tmp_path: Path) -> None:
    fixture = FIXTURE_ROOT / "minimal.json"

    assert main([
        "--root",
        str(tmp_path),
        "contract",
        "validate",
        "--type",
        WORK_BRIEF_CONTRACT_VERSION,
        str(fixture),
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "contract_type": WORK_BRIEF_CONTRACT_VERSION,
        "errors": [],
        "ok": True,
        "path": str(fixture),
    }
    assert list(tmp_path.iterdir()) == []


def test_contract_cli_rejects_embedded_route(capsys) -> None:
    fixture = FIXTURE_ROOT / "negative-embedded-route.json"

    assert main([
        "contract",
        "validate",
        "--type",
        WORK_BRIEF_CONTRACT_VERSION,
        str(fixture),
        "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert any("$.route: additional property" in item for item in payload["errors"])


def test_brief_add_dry_run_is_zero_mutation(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_for_target(tmp_path, task_id)
    before = _counts(root)

    assert main([
        "--root", str(root), "brief", "add", str(brief),
        "--summary", "Work Brief draft", "--dry-run", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["planned"]["target"] == {"type": "task", "id": task_id}
    assert _counts(root) == before
    assert not (root / ".project-loop" / "evidence" / "work-briefs").exists()


def test_brief_add_show_approve_and_idempotency(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_for_target(tmp_path, task_id)
    before = _counts(root)

    assert main([
        "--root", str(root), "brief", "add", str(brief),
        "--summary", "Work Brief draft", "--json",
    ]) == 0
    added = json.loads(capsys.readouterr().out)
    evidence_id = added["evidence"]["id"]
    after_add = _counts(root)

    assert after_add == {
        "evidence": before["evidence"] + 1,
        "events": before["events"] + 1,
        "outbox": before["outbox"] + 1,
        "links": before["links"] + 1,
    }
    assert main([
        "--root", str(root), "brief", "show", "--evidence", evidence_id, "--json",
    ]) == 0
    shown = json.loads(capsys.readouterr().out)["work_brief"]
    assert shown["approved"] is False
    assert shown["health"] == "ok"

    assert main([
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "human:owner", "--reason", "Reviewed the execution input",
        "--dry-run", "--json",
    ]) == 0
    capsys.readouterr()
    assert _counts(root) == after_add

    approve_args = [
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "human:owner", "--reason", "Reviewed the execution input", "--json",
    ]
    assert main(approve_args) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["changed"] is True
    after_approve = _counts(root)
    assert after_approve["events"] == after_add["events"] + 1
    assert after_approve["outbox"] == after_add["outbox"] + 1

    assert main(approve_args) == 0
    duplicate = json.loads(capsys.readouterr().out)
    assert duplicate["changed"] is False
    assert _counts(root) == after_approve

    assert main([
        "--root", str(root), "brief", "show", "--target", f"task:{task_id}", "--json",
    ]) == 0
    target_view = json.loads(capsys.readouterr().out)
    assert target_view["current"]["evidence_id"] == evidence_id
    assert target_view["current"]["approval"]["actor"] == "human:owner"

    before_read_views = _counts(root)
    paths = resolve_paths(root)
    context = pack_context_for_task(
        paths,
        task_id=task_id,
        now="2026-07-11T00:00:00+00:00",
    )
    handoff = build_handoff_packet(
        paths,
        target_id=task_id,
        now="2026-07-11T00:00:00+00:00",
    )

    assert context["work_brief"] == {
        "contract_version": "work-brief-context/v1",
        "evidence_id": evidence_id,
        "evidence_ref": f"evidence:{evidence_id}",
        "brief_id": "WB-0001",
        "revision": 1,
        "target": {"type": "task", "id": task_id},
        "artifact_sha256": added["evidence"]["artifact_sha256"],
        "path": added["evidence"]["path"],
        "summary": "Work Brief draft",
        "approval_event_id": approved["event_id"],
        "approved_by": "human:owner",
        "approval_actor_kind": "human",
        "approval_recorder_kind": "human",
        "approval_recorded_by": "human:owner",
        "approval_source": "pcl brief approve",
        "approval_source_kind": "cli",
        "approval_source_ref": "",
        "approval_bound_sha256": added["evidence"]["artifact_sha256"],
        "approved_at": target_view["current"]["approval"]["created_at"],
        "claims_are_facts": False,
    }
    assert "work_brief" in context["included_sections"]
    assert handoff["target"]["work_brief_ref"] == f"evidence:{evidence_id}"
    assert handoff["restart_context"]["acceptance_status"] == "work_brief_linked"
    assert handoff["restart_context"]["approval_provenance"] == {
        "event_id": approved["event_id"],
        "actor_kind": "human",
        "actor": "human:owner",
        "recorder_kind": "human",
        "recorder": "human:owner",
        "source": "pcl brief approve",
        "source_kind": "cli",
        "source_ref": "",
        "timestamp": target_view["current"]["approval"]["timestamp"],
        "target": {"type": "task", "id": task_id},
        "bound_evidence": {
            "id": evidence_id,
            "artifact_sha256": added["evidence"]["artifact_sha256"],
        },
    }
    assert any(
        item["ref"] == f"evidence:{evidence_id}" and item["kind"] == "work-brief/v1"
        for item in handoff["context_refs"]
    )
    assert _counts(root) == before_read_views


def test_agent_review_is_hash_bound_but_cannot_approve_human_gate(
    tmp_path: Path,
    capsys,
) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief = _brief_for_target(tmp_path, task_id)
    assert main([
        "--root", str(root), "brief", "add", str(brief),
        "--summary", "Agent review input", "--json",
    ]) == 0
    evidence = json.loads(capsys.readouterr().out)["evidence"]
    evidence_id = evidence["id"]
    before = _counts(root)

    assert main([
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "human:owner", "--actor-kind", "agent",
        "--reason", "Mismatched authority", "--json",
    ]) == 2
    mismatch = json.loads(capsys.readouterr().out)
    assert mismatch["error"]["code"] == "invalid_input"
    assert _counts(root) == before

    assert main([
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "agent:codex", "--actor-kind", "agent",
        "--reason", "Self review passed", "--json",
    ]) == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["error"]["code"] == "work_brief_human_approval_required"
    assert _counts(root) == before

    assert main([
        "--root", str(root), "brief", "review", evidence_id,
        "--actor", "agent:codex", "--actor-kind", "agent",
        "--reason", "Self review passed", "--json",
    ]) == 0
    reviewed = json.loads(capsys.readouterr().out)
    assert reviewed["review"]["actor_kind"] == "agent"
    assert reviewed["review"]["bound_evidence"] == {
        "id": evidence_id,
        "artifact_sha256": evidence["artifact_sha256"],
    }

    assert main([
        "--root", str(root), "brief", "show", "--evidence", evidence_id, "--json",
    ]) == 0
    shown = json.loads(capsys.readouterr().out)["work_brief"]
    assert shown["approved"] is False
    assert shown["approval"] is None
    assert [item["actor_kind"] for item in shown["reviews"]] == ["agent"]

    before_mediated_approval = _counts(root)
    assert main([
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "human:owner", "--actor-kind", "human",
        "--recorded-by", "agent:codex", "--recorder-kind", "agent",
        "--reason", "Conversation approval without source", "--json",
    ]) == 2
    missing_source = json.loads(capsys.readouterr().out)
    assert missing_source["error"]["code"] == "invalid_input"
    assert _counts(root) == before_mediated_approval

    assert main([
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "human:owner", "--actor-kind", "human",
        "--recorded-by", "agent:codex", "--recorder-kind", "agent",
        "--source-kind", "conversation",
        "--source-ref", "conversation:test-user-explicit-approval",
        "--reason", "Explicit human approval", "--json",
    ]) == 0
    approved = json.loads(capsys.readouterr().out)
    receipt = approved["approval"]["approval_provenance"]
    assert receipt["actor_kind"] == "human"
    assert receipt["actor"] == "human:owner"
    assert receipt["recorder_kind"] == "agent"
    assert receipt["recorder"] == "agent:codex"
    assert receipt["source"] == "conversation"
    assert receipt["source_kind"] == "conversation"
    assert receipt["source_ref"] == "conversation:test-user-explicit-approval"
    assert receipt["target"] == {"type": "task", "id": task_id}
    assert receipt["bound_evidence"]["artifact_sha256"] == evidence["artifact_sha256"]

    assert main(["--root", str(root), "render", "--json"]) == 0
    capsys.readouterr()
    dashboard = json.loads(
        (root / ".project-loop" / "dashboard" / "dashboard-data.json").read_text(
            encoding="utf-8"
        )
    )
    assert [item["actor_kind"] for item in dashboard["approval_provenance"][:2]] == [
        "human",
        "agent",
    ]


def test_second_approval_for_target_fails_without_mutation(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    first = _brief_for_target(tmp_path, task_id, brief_id="WB-0001")
    second = _brief_for_target(tmp_path, task_id, brief_id="WB-0002")

    evidence_ids: list[str] = []
    for path in (first, second):
        assert main([
            "--root", str(root), "brief", "add", str(path),
            "--summary", path.stem, "--json",
        ]) == 0
        evidence_ids.append(json.loads(capsys.readouterr().out)["evidence"]["id"])
    assert main([
        "--root", str(root), "brief", "approve", evidence_ids[0],
        "--actor", "human:owner", "--reason", "First approval", "--json",
    ]) == 0
    capsys.readouterr()
    before = _counts(root)

    assert main([
        "--root", str(root), "brief", "approve", evidence_ids[1],
        "--actor", "human:owner", "--reason", "Conflicting approval", "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["error"]["code"] == "work_brief_approval_conflict"
    assert _counts(root) == before


def test_unknown_target_rejected_before_artifact_or_state_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    root, _ = _initialized_target(tmp_path)
    brief = _brief_for_target(tmp_path, "T-9999")
    before = _counts(root)

    assert main([
        "--root", str(root), "brief", "add", str(brief),
        "--summary", "Unknown target", "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["error"]["code"] == "work_brief_unknown_target"
    assert _counts(root) == before
    assert not (root / ".project-loop" / "evidence" / "work-briefs").exists()


def test_approved_artifact_drift_is_visible(tmp_path: Path, capsys) -> None:
    root, task_id = _initialized_target(tmp_path)
    brief_path = _brief_for_target(tmp_path, task_id)
    assert main([
        "--root", str(root), "brief", "add", str(brief_path),
        "--summary", "Drift test", "--json",
    ]) == 0
    evidence = json.loads(capsys.readouterr().out)["evidence"]
    evidence_id = evidence["id"]
    assert main([
        "--root", str(root), "brief", "approve", evidence_id,
        "--actor", "human:owner", "--reason", "Approve before drift", "--json",
    ]) == 0
    capsys.readouterr()
    artifact = root / evidence["path"]
    value = json.loads(artifact.read_text(encoding="utf-8"))
    changed = deepcopy(value)
    changed["intent"]["desired_outcome"] = "Changed after approval"
    artifact.write_text(json.dumps(changed), encoding="utf-8")

    assert main([
        "--root", str(root), "brief", "show", "--evidence", evidence_id, "--json",
    ]) == 0
    shown = json.loads(capsys.readouterr().out)["work_brief"]

    assert shown["approved"] is False
    assert shown["health"] == "warning"
    assert {item["code"] for item in shown["findings"]} == {"approval_hash_mismatch"}
