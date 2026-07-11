from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.contracts.route_override import (
    ROUTE_OVERRIDE_CONTRACT_VERSION,
    route_override_schema,
    validate_route_override,
)
from pcl.context import pack_context_for_task
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.route_overrides import current_route, override_route
from pcl.resume import build_handoff_packet
from pcl.start import start_work
from pcl.work_briefs import add_work_brief, approve_work_brief


def _project(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "project"
    root.mkdir()
    paths = resolve_paths(root)
    init_project(paths)
    config = root / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('  test: ""', '  test: "pytest"'),
        encoding="utf-8",
    )
    started = start_work(paths, intent="Implement audited route overrides")
    return root, str(started["result"]["created_ids"]["task"])


def _brief_file(tmp_path: Path, task_id: str) -> Path:
    value = {
        "contract_version": "work-brief/v1",
        "brief_id": "WB-0001",
        "revision": 1,
        "target": {"type": "task", "id": task_id},
        "intent": {"problem": "An exception is needed.", "desired_outcome": "Audit it."},
        "acceptance_criteria": [
            {
                "id": "AC-01",
                "text": "The override is immutable.",
                "critical": True,
                "evidence_refs": [],
            }
        ],
        "constraints": [],
        "non_goals": [],
        "assumptions": [],
        "created_at": "2026-07-11T00:00:00Z",
        "created_by": "human:test-owner",
    }
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _approve_brief(root: Path, brief_file: Path) -> None:
    paths = resolve_paths(root)
    added = add_work_brief(paths, file=str(brief_file), summary="Override input")
    approve_work_brief(
        paths,
        evidence_id=str(added["evidence"]["id"]),
        actor="human:test-owner",
        reason="Fixture approval",
    )


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("evidence", "events", "outbox_records", "evidence_links")
        }
    finally:
        conn.close()


def test_route_override_schema_is_packaged() -> None:
    schema = route_override_schema()

    assert schema["$id"].endswith("route-override-v1.schema.json")
    assert schema["properties"]["requested_profile"]["enum"] == [
        "direct",
        "discover",
        "assure",
    ]


def test_override_preview_is_deterministic_and_zero_mutation(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    paths = resolve_paths(root)
    before = _counts(root)

    first = override_route(
        paths,
        target_ref=f"task:{task_id}",
        requested_profile="discover",
        actor="human:test-owner",
        reason="Explore an ambiguous boundary",
        dry_run=True,
    )
    second = override_route(
        paths,
        target_ref=f"task:{task_id}",
        requested_profile="discover",
        actor="human:test-owner",
        reason="Explore an ambiguous boundary",
        dry_run=True,
    )

    assert first == second
    assert first["changed"] is False
    assert first["planned"]["original_recommendation"]["profile"] == "direct"
    assert first["planned"]["effective_recommendation"]["profile"] == "discover"
    assert _counts(root) == before


def test_override_apply_is_one_audited_idempotent_mutation(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    paths = resolve_paths(root)
    before = _counts(root)
    kwargs = {
        "target_ref": f"task:{task_id}",
        "requested_profile": "discover",
        "actor": "human:test-owner",
        "reason": "Explore an ambiguous boundary",
    }

    applied = override_route(paths, **kwargs)
    after = _counts(root)

    assert applied["changed"] is True
    assert validate_route_override(applied["override"]).ok is True
    assert after == {
        "evidence": before["evidence"] + 3,
        "events": before["events"] + 1,
        "outbox_records": before["outbox_records"] + 1,
        "evidence_links": before["evidence_links"] + 3,
    }
    assert applied["override"]["original_recommendation_ref"].startswith("evidence:E-")
    assert applied["override"]["original_resolution_ref"].startswith("evidence:E-")
    assert applied["override"]["effective_resolution"]["profile"] == "discover"

    duplicate = override_route(paths, **kwargs)
    assert duplicate["changed"] is False
    assert duplicate["override"]["override_digest"] == applied["override"]["override_digest"]
    assert _counts(root) == after


def test_permission_downgrade_fails_closed_without_trace(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    before = _counts(root)

    assert main([
        "--root", str(root), "route", "override",
        "--target", f"task:{task_id}",
        "--profile", "direct",
        "--actor", "human:test-owner",
        "--reason", "Attempt unsafe downgrade",
        "--changed-path", "src/auth/login.py",
        "--json",
    ]) != 0

    assert _counts(root) == before


def test_current_preserves_historical_resolution_after_policy_file_changes(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    paths = resolve_paths(root)
    applied = override_route(
        paths,
        target_ref=f"task:{task_id}",
        requested_profile="discover",
        actor="human:test-owner",
        reason="Historical policy fixture",
    )

    current = current_route(paths, target_ref=f"task:{task_id}")

    assert current["overridden"] is True
    assert current["effective"]["resolution"] == applied["override"]["effective_resolution"]
    assert current["original"]["recommendation_ref"] == applied["override"][
        "original_recommendation_ref"
    ]


def test_route_override_cli_and_contract_validation(tmp_path: Path, capsys) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))

    assert main([
        "--root", str(root), "route", "override",
        "--target", f"task:{task_id}",
        "--profile", "discover",
        "--actor", "human:test-owner",
        "--reason", "CLI fixture",
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    artifact = root / payload["evidence"]["override"]["path"]

    assert main([
        "contract", "validate", "--type", ROUTE_OVERRIDE_CONTRACT_VERSION,
        str(artifact), "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert main([
        "--root", str(root), "route", "current",
        "--target", f"task:{task_id}", "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["overridden"] is True


def test_override_refs_flow_into_context_and_handoff_packets(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    paths = resolve_paths(root)
    applied = override_route(
        paths,
        target_ref=f"task:{task_id}",
        requested_profile="discover",
        actor="human:test-owner",
        reason="Packet integration fixture",
    )
    override_ref = f"evidence:{applied['evidence']['override']['id']}"

    context_pack = pack_context_for_task(
        paths,
        task_id=task_id,
        now="2026-07-11T00:00:00Z",
    )
    handoff = build_handoff_packet(
        paths,
        target_id=task_id,
        now="2026-07-11T00:00:00Z",
    )

    assert context_pack["adaptive_route"]["override_ref"] == override_ref
    assert "## Adaptive Route" in context_pack["markdown"]
    assert override_ref in {item["ref"] for item in handoff["context_refs"]}
