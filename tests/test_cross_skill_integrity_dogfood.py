from __future__ import annotations

import json
from pathlib import Path
import shutil

from pcl.cli import main
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cross_skill_dogfood"
WORK_BRIEF_FIXTURE = Path(__file__).parent / "fixtures" / "work_brief" / "minimal.json"


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _setup_acceptance(root: Path, capsys) -> tuple[str, str]:
    init_project(resolve_paths(root))
    assert main([
        "--root", str(root), "feature", "add", "--name", "Cross-skill deliverable",
        "--surface", "artifact:landing-page",
    ]) == 0
    feature_id = capsys.readouterr().out.strip()
    assert main([
        "--root", str(root), "story", "draft", "--feature", feature_id,
        "--actor", "operator", "--goal", "accept only a complete deliverable",
        "--expected-behavior", "known failed reports cannot be hidden by positive evidence",
    ]) == 0
    story_id = capsys.readouterr().out.strip()
    assert main([
        "--root", str(root), "story", "approve", story_id,
        "--summary", "Cross-skill acceptance approved",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(root), "test", "plan", "--feature", feature_id,
        "--story", story_id, "--type", "e2e",
        "--scenario", "external skill reports prototype or complete",
        "--expected", "only complete with every required passing report may pass",
    ]) == 0
    return feature_id, capsys.readouterr().out.strip()


def _copy_fixture(root: Path, name: str) -> Path:
    work_root = root / "work" / "cross-skill"
    shutil.copytree(FIXTURE_ROOT / name, work_root)
    return work_root


def _add_report_evidence(root: Path, report: Path, capsys) -> str:
    assert main([
        "--root", str(root), "evidence", "add", "--file", str(report),
        "--summary", report.stem, "--json",
    ]) == 0
    return str(_json(capsys)["evidence"]["id"])


def _record_set(
    root: Path,
    test_id: str,
    work_root: Path,
    capsys,
    *,
    include_coordinate: bool,
) -> str:
    reports = work_root / "reports"
    ids = {
        kind: _add_report_evidence(root, reports / f"{kind}.json", capsys)
        for kind in (
            ["completion_verdict", "coordinate_report", "responsive_report"]
            if include_coordinate
            else ["completion_verdict", "responsive_report"]
        )
    }
    args = [
        "--root", str(root), "evidence-set", "record",
        "--target", f"test_case:{test_id}", "--work-root", str(work_root),
        "--manifest", str(reports / "report-manifest.json"),
        "--required-kind", "completion_verdict",
        "--required-kind", "coordinate_report",
        "--required-kind", "responsive_report",
        "--include", f"completion_verdict={ids['completion_verdict']}:verdict",
        "--include", f"responsive_report={ids['responsive_report']}:responsive",
        "--summary", "Cross-skill completion receipt", "--json",
    ]
    if include_coordinate:
        args.extend(["--include", f"coordinate_report={ids['coordinate_report']}:geometry"])
    assert main(args) == 0
    return str(_json(capsys)["evidence"]["id"])


def _mutation_snapshot(root: Path, feature_id: str, test_id: str) -> dict:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "feature_status": conn.execute(
                "SELECT status FROM features WHERE id = ?", (feature_id,)
            ).fetchone()[0],
            "test_status": conn.execute(
                "SELECT status FROM test_cases WHERE id = ?", (test_id,)
            ).fetchone()[0],
            "links": conn.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "outbox": conn.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0],
        }
    finally:
        conn.close()


def test_incomplete_prototype_cannot_pass_and_next_is_not_idle(
    tmp_path: Path,
    capsys,
) -> None:
    feature_id, test_id = _setup_acceptance(tmp_path, capsys)
    work_root = _copy_fixture(tmp_path, "incomplete")
    evidence_set_id = _record_set(
        tmp_path, test_id, work_root, capsys, include_coordinate=False
    )
    before = _mutation_snapshot(tmp_path, feature_id, test_id)

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "Prototype must not pass", "--evidence-id", evidence_set_id,
        "--completion-policy", str(FIXTURE_ROOT / "completion-policy.json"), "--json",
    ]) == 2
    rejected = _json(capsys)
    evaluation = rejected["error"]["details"]["evaluation"]
    assert rejected["error"]["code"] == "completion_policy_failed"
    assert evaluation["status"] == "failed"
    assert {item["code"] for item in evaluation["findings"]} >= {
        "evidence_set_incomplete",
        "predicate_failed",
    }
    assert _mutation_snapshot(tmp_path, feature_id, test_id) == before

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json(capsys)
    assert action["type"] != "idle"
    assert action["target"]["id"] in {feature_id, test_id}


def test_complete_fixture_passes_with_evidence_and_mediated_approval_chain(
    tmp_path: Path,
    capsys,
) -> None:
    feature_id, test_id = _setup_acceptance(tmp_path, capsys)
    work_root = _copy_fixture(tmp_path, "complete")
    evidence_set_id = _record_set(
        tmp_path, test_id, work_root, capsys, include_coordinate=True
    )

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "Complete deliverable accepted", "--evidence-id", evidence_set_id,
        "--completion-policy", str(FIXTURE_ROOT / "completion-policy.json"), "--json",
    ]) == 0
    passed = _json(capsys)
    assert passed["status"] == "passing"
    assert passed["feature_status"] == "passing"
    assert passed["completion_evaluation"]["status"] == "passed"

    brief = json.loads(WORK_BRIEF_FIXTURE.read_text(encoding="utf-8"))
    brief["brief_id"] = "WB-0002"
    brief["target"] = {"type": "feature", "id": feature_id}
    brief_path = tmp_path / "cross-skill-review-brief.json"
    brief_path.write_text(json.dumps(brief, sort_keys=True), encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "brief", "add", str(brief_path),
        "--summary", "Cross-skill review packet", "--json",
    ]) == 0
    brief_evidence_id = str(_json(capsys)["evidence"]["id"])
    assert main([
        "--root", str(tmp_path), "brief", "approve", brief_evidence_id,
        "--actor", "human:reviewer", "--actor-kind", "human",
        "--recorded-by", "agent:dogfood", "--recorder-kind", "agent",
        "--source-kind", "conversation",
        "--source-ref", "conversation:fixture-explicit-approval",
        "--reason", "Complete fixture review approved", "--json",
    ]) == 0
    approval = _json(capsys)["approval"]["approval_provenance"]
    assert approval["actor_kind"] == "human"
    assert approval["recorder_kind"] == "agent"
    assert approval["source_kind"] == "conversation"
    assert approval["bound_evidence"]["id"] == brief_evidence_id

    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    action = _json(capsys)
    assert action["type"] == "review_passing_feature_completion"
    assert action["target"]["completion_status"] == "ready_for_explicit_done_review"
    assert action["target"]["completion_blockers"] == []
