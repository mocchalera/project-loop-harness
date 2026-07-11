from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.contracts.route_recommendation import (
    ROUTE_RECOMMENDATION_CONTRACT_VERSION,
    canonical_route_recommendation_json,
    route_recommendation_schema,
    validate_route_recommendation,
)
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths
from pcl.routing import recommend_route
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
    started = start_work(paths, intent="Implement deterministic routing")
    return root, str(started["result"]["created_ids"]["task"])


def _brief_file(
    tmp_path: Path,
    task_id: str,
    *,
    brief_id: str = "WB-0001",
    assumptions: list[dict] | None = None,
) -> Path:
    value = {
        "contract_version": "work-brief/v1",
        "brief_id": brief_id,
        "revision": 1,
        "target": {"type": "task", "id": task_id},
        "intent": {
            "problem": "The route must be reproducible.",
            "desired_outcome": "The same input produces the same route.",
        },
        "acceptance_criteria": [
            {
                "id": "AC-01",
                "text": "The resolver is deterministic.",
                "critical": True,
                "evidence_refs": [],
            }
        ],
        "constraints": [],
        "non_goals": ["Do not invoke an LLM."],
        "assumptions": assumptions or [],
        "created_at": "2026-07-11T00:00:00Z",
        "created_by": "test:operator",
    }
    path = tmp_path / f"{brief_id.lower()}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _approve_brief(root: Path, brief_file: Path) -> str:
    paths = resolve_paths(root)
    added = add_work_brief(paths, file=str(brief_file), summary="Routing input")
    evidence_id = str(added["evidence"]["id"])
    approve_work_brief(
        paths,
        evidence_id=evidence_id,
        actor="human:test-owner",
        reason="Fixture approval",
    )
    return evidence_id


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


def test_route_schema_is_packaged() -> None:
    schema = route_recommendation_schema()

    assert schema["$id"].endswith("route-recommendation-v1.schema.json")
    assert schema["properties"]["profile"]["enum"] == ["direct", "discover", "assure"]


def test_missing_brief_recommends_discover_without_mutation(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    paths = resolve_paths(root)
    before = _counts(root)

    first = recommend_route(paths, target_ref=f"task:{task_id}")
    second = recommend_route(paths, target_ref=f"task:{task_id}")

    assert first == second
    recommendation = first["recommendation"]
    assert recommendation["profile"] == "discover"
    assert recommendation["risk_level"] == "R1"
    assert {"missing_acceptance", "missing_work_brief"}.issubset(
        recommendation["reason_codes"]
    )
    assert _counts(root) == before


def test_approved_clear_brief_recommends_direct_deterministically(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    brief_file = _brief_file(tmp_path, task_id)
    evidence_id = _approve_brief(root, brief_file)
    paths = resolve_paths(root)
    before = _counts(root)

    first = recommend_route(paths, target_ref=f"task:{task_id}")["recommendation"]
    second = recommend_route(paths, target_ref=f"task:{task_id}")["recommendation"]

    assert canonical_route_recommendation_json(first) == canonical_route_recommendation_json(second)
    assert first["profile"] == "direct"
    assert first["risk_level"] == "R0"
    assert first["reason_codes"] == ["clear_acceptance"]
    assert first["work_brief_ref"] == f"evidence:{evidence_id}"
    assert validate_route_recommendation(first).ok is True
    assert _counts(root) == before


def test_explicit_unapproved_brief_is_discover(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    brief_file = _brief_file(tmp_path, task_id)

    result = recommend_route(
        resolve_paths(root),
        target_ref=f"task:{task_id}",
        brief_file=str(brief_file),
    )["recommendation"]

    assert result["profile"] == "discover"
    assert result["work_brief_ref"] is None
    assert "unapproved_brief_input" in result["reason_codes"]


def test_auth_path_normalization_recommends_assure_equivalently(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    paths = resolve_paths(root)

    posix = recommend_route(
        paths,
        target_ref=f"task:{task_id}",
        changed_paths=["src/auth/login.py"],
    )["recommendation"]
    windows = recommend_route(
        paths,
        target_ref=f"task:{task_id}",
        changed_paths=["SRC\\AUTH\\login.py"],
    )["recommendation"]

    assert posix == windows
    assert posix["profile"] == "assure"
    assert posix["risk_level"] == "R3"
    assert "auth_or_permission_change" in posix["reason_codes"]
    assert posix["signals"]["model_self_assessment_used"] is False


def test_record_is_explicit_and_idempotent(tmp_path: Path) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))
    paths = resolve_paths(root)
    before = _counts(root)

    read_only = recommend_route(paths, target_ref=f"task:{task_id}")
    assert read_only["recorded"] is False
    assert _counts(root) == before

    recorded = recommend_route(paths, target_ref=f"task:{task_id}", record=True)
    after = _counts(root)
    assert recorded["changed"] is True
    assert recorded["recorded"] is True
    assert after == {
        "evidence": before["evidence"] + 1,
        "events": before["events"] + 1,
        "outbox": before["outbox"] + 1,
        "links": before["links"] + 1,
    }
    duplicate = recommend_route(paths, target_ref=f"task:{task_id}", record=True)
    assert duplicate["changed"] is False
    assert duplicate["evidence"]["id"] == recorded["evidence"]["id"]
    assert _counts(root) == after


def test_route_cli_and_contract_validation(tmp_path: Path, capsys) -> None:
    root, task_id = _project(tmp_path)
    _approve_brief(root, _brief_file(tmp_path, task_id))

    assert main([
        "--root", str(root), "route", "recommend",
        "--target", f"task:{task_id}", "--json",
    ]) == 0
    recommendation = json.loads(capsys.readouterr().out)["recommendation"]
    artifact = tmp_path / "route.json"
    artifact.write_text(json.dumps(recommendation), encoding="utf-8")

    assert main([
        "contract", "validate", "--type", ROUTE_RECOMMENDATION_CONTRACT_VERSION,
        str(artifact), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["contract_type"] == ROUTE_RECOMMENDATION_CONTRACT_VERSION
