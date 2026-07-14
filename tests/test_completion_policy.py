from __future__ import annotations

import json
from pathlib import Path

from pcl.cli import main
from pcl.contracts.completion_policy import (
    COMPLETION_POLICY_CONTRACT_VERSION,
    completion_policy_schema,
)
from pcl.db import connect
from pcl.init_project import init_project
from pcl.paths import resolve_paths


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "completion_policy"


def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _counts(root: Path) -> dict[str, int]:
    conn = connect(root / ".project-loop" / "project.db")
    try:
        return {
            "tests": int(conn.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0]),
            "evidence": int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
            "links": int(conn.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0]),
            "events": int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "outbox": int(conn.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0]),
        }
    finally:
        conn.close()


def _feature_story_test(root: Path, capsys) -> tuple[str, str, str]:
    assert main([
        "--root", str(root), "feature", "add", "--name", "Completion policy",
        "--surface", "cli:pcl completion",
    ]) == 0
    feature_id = capsys.readouterr().out.strip()
    assert main([
        "--root", str(root), "story", "draft", "--feature", feature_id,
        "--actor", "operator", "--goal", "trust external completion",
        "--expected-behavior", "prototype cannot satisfy complete",
    ]) == 0
    story_id = capsys.readouterr().out.strip()
    assert main([
        "--root", str(root), "story", "approve", story_id,
        "--summary", "approved acceptance",
    ]) == 0
    capsys.readouterr()
    assert main([
        "--root", str(root), "test", "plan", "--feature", feature_id,
        "--story", story_id, "--type", "acceptance",
        "--scenario", "evaluate verdict", "--expected", "complete only",
    ]) == 0
    test_id = capsys.readouterr().out.strip()
    return feature_id, story_id, test_id


def _policy(tmp_path: Path) -> Path:
    path = tmp_path / "completion-policy.json"
    path.write_text(json.dumps({
        "contract_version": "completion-policy/v1",
        "policy_id": "lp-complete",
        "required_evidence_set_status": "complete",
        "predicates": [
            {
                "id": "findings-empty",
                "report_kind": "completion_verdict",
                "json_path": "$.findings",
                "operator": "empty",
            },
            {
                "id": "verdict-complete",
                "report_kind": "completion_verdict",
                "json_path": "$.status",
                "operator": "equals",
                "expected": "complete",
            },
        ],
    }, sort_keys=True), encoding="utf-8")
    return path


def _evidence_set(
    root: Path,
    test_id: str,
    capsys,
    *,
    verdict: str,
    include_box: bool = True,
) -> str:
    work_root = root / "work" / "lp"
    reports = work_root / "reports"
    reports.mkdir(parents=True)
    verdict_path = reports / "completion-verdict.json"
    verdict_path.write_text(
        json.dumps({"status": verdict, "findings": []}, sort_keys=True),
        encoding="utf-8",
    )
    box_path = reports / "box-report.json"
    box_path.write_text(json.dumps({"pass_rate": 1.0}), encoding="utf-8")
    manifest = reports / "report-manifest.json"
    manifest.write_text(json.dumps({
        "contract_version": "evidence-report-manifest/v1",
        "reports": [
            {"kind": "box_report", "path": "reports/box-report.json", "status": "pass"},
            {"kind": "completion_verdict", "path": "reports/completion-verdict.json", "status": "pass"},
        ],
    }, sort_keys=True), encoding="utf-8")
    evidence_ids: dict[str, str] = {}
    for kind, report_path in (("box_report", box_path), ("completion_verdict", verdict_path)):
        assert main([
            "--root", str(root), "evidence", "add", "--file", str(report_path),
            "--summary", kind, "--json",
        ]) == 0
        evidence_ids[kind] = _json(capsys)["evidence"]["id"]
    args = [
        "--root", str(root), "evidence-set", "record",
        "--target", f"test_case:{test_id}", "--work-root", str(work_root),
        "--manifest", str(manifest), "--required-kind", "box_report",
        "--required-kind", "completion_verdict",
        "--include", f"completion_verdict={evidence_ids['completion_verdict']}:verdict",
        "--summary", "completion receipt", "--json",
    ]
    if include_box:
        args.extend(["--include", f"box_report={evidence_ids['box_report']}:geometry"])
    assert main(args) == 0
    return str(_json(capsys)["evidence"]["id"])


def _pass_with_adhoc_evidence(root: Path, test_id: str, capsys) -> str:
    report = root / "legacy-pass.json"
    report.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    assert main([
        "--root", str(root), "evidence", "add", "--file", str(report),
        "--summary", "legacy passing proof", "--json",
    ]) == 0
    evidence_id = str(_json(capsys)["evidence"]["id"])
    assert main([
        "--root", str(root), "test", "pass", test_id,
        "--summary", "legacy pass", "--evidence-id", evidence_id, "--json",
    ]) == 0
    assert _json(capsys)["evidence_id"] == evidence_id
    return evidence_id


def test_completion_policy_schema_is_packaged() -> None:
    schema = completion_policy_schema()
    assert schema["$id"].endswith("completion-policy-v1.schema.json")
    assert schema["properties"]["contract_version"]["const"] == COMPLETION_POLICY_CONTRACT_VERSION


def test_completion_policy_fixture_validates_without_project_state(tmp_path: Path, capsys) -> None:
    fixture = FIXTURE_ROOT / "minimal.json"
    assert main([
        "--root", str(tmp_path), "contract", "validate", "--type",
        COMPLETION_POLICY_CONTRACT_VERSION, str(fixture), "--json",
    ]) == 0
    assert _json(capsys)["ok"] is True
    assert list(tmp_path.iterdir()) == []

    value = json.loads(fixture.read_text(encoding="utf-8"))
    value["predicates"][0]["operator"] = "execute"
    invalid = tmp_path / "invalid-policy.json"
    invalid.write_text(json.dumps(value), encoding="utf-8")
    assert main([
        "contract", "validate", "--type", COMPLETION_POLICY_CONTRACT_VERSION,
        str(invalid), "--json",
    ]) == 1
    assert any("unsupported operator" in item for item in _json(capsys)["errors"])


def test_prototype_verdict_rejects_test_pass_with_zero_traces(tmp_path: Path, capsys) -> None:
    init_project(resolve_paths(tmp_path))
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_set_id = _evidence_set(tmp_path, test_id, capsys, verdict="prototype")
    policy = _policy(tmp_path)
    before = _counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "missing policy", "--evidence-id", evidence_set_id, "--json",
    ]) == 2
    assert _json(capsys)["error"]["code"] == "completion_policy_required"
    assert _counts(tmp_path) == before

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "must reject", "--evidence-id", evidence_set_id,
        "--completion-policy", str(policy), "--json",
    ]) == 2
    payload = _json(capsys)

    assert payload["error"]["code"] == "completion_policy_failed"
    evaluation = payload["error"]["details"]["evaluation"]
    assert evaluation["status"] == "failed"
    assert evaluation["findings"] == [
        {
            "code": "predicate_failed",
            "predicate_id": "verdict-complete",
            "report_kind": "completion_verdict",
        }
    ]
    assert _counts(tmp_path) == before


def test_incomplete_evidence_set_rejects_even_complete_verdict(tmp_path: Path, capsys) -> None:
    init_project(resolve_paths(tmp_path))
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_set_id = _evidence_set(
        tmp_path,
        test_id,
        capsys,
        verdict="complete",
        include_box=False,
    )
    policy = _policy(tmp_path)
    before = _counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "must reject incomplete", "--evidence-id", evidence_set_id,
        "--completion-policy", str(policy), "--json",
    ]) == 2
    evaluation = _json(capsys)["error"]["details"]["evaluation"]
    assert any(item["code"] == "evidence_set_incomplete" for item in evaluation["findings"])
    assert _counts(tmp_path) == before


def test_missing_policy_report_and_drifted_report_reject_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    init_project(resolve_paths(tmp_path))
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_set_id = _evidence_set(tmp_path, test_id, capsys, verdict="complete")
    policy = _policy(tmp_path)
    value = json.loads(policy.read_text(encoding="utf-8"))
    value["predicates"][0]["report_kind"] = "release_verdict"
    value["predicates"].sort(key=lambda item: (item["id"], item["report_kind"], item["json_path"]))
    policy.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    before = _counts(tmp_path)
    args = [
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "reject missing report", "--evidence-id", evidence_set_id,
        "--completion-policy", str(policy), "--json",
    ]
    assert main(args) == 2
    evaluation = _json(capsys)["error"]["details"]["evaluation"]
    assert any(item["code"] == "predicate_report_missing" for item in evaluation["findings"])
    assert _counts(tmp_path) == before

    policy = _policy(tmp_path)
    verdict_path = tmp_path / "work" / "lp" / "reports" / "completion-verdict.json"
    verdict_path.write_text(json.dumps({"status": "complete", "findings": ["drift"]}), encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "reject drift", "--evidence-id", evidence_set_id,
        "--completion-policy", str(policy), "--json",
    ]) == 2
    evaluation = _json(capsys)["error"]["details"]["evaluation"]
    assert any(item["code"] == "report_hash_mismatch" for item in evaluation["findings"])
    assert _counts(tmp_path) == before


def test_complete_verdict_passes_and_records_evaluation(tmp_path: Path, capsys) -> None:
    init_project(resolve_paths(tmp_path))
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    evidence_set_id = _evidence_set(tmp_path, test_id, capsys, verdict="complete")
    policy = _policy(tmp_path)
    before_preview = _counts(tmp_path)

    assert main([
        "--root", str(tmp_path), "completion", "evaluate",
        "--policy", str(policy), "--evidence-set", evidence_set_id,
        "--test", test_id, "--json",
    ]) == 0
    preview = _json(capsys)
    assert preview["changed"] is False
    assert preview["evaluation"]["status"] == "passed"
    assert _counts(tmp_path) == before_preview
    assert main([
        "--root", str(tmp_path), "completion", "evaluate",
        "--policy", str(policy), "--evidence-set", evidence_set_id,
        "--test", test_id, "--json",
    ]) == 0
    assert _json(capsys) == preview
    assert _counts(tmp_path) == before_preview

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "complete", "--evidence-id", evidence_set_id,
        "--completion-policy", str(policy), "--json",
    ]) == 0
    passed = _json(capsys)
    assert passed["completion_evaluation"] == preview["evaluation"]

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        links = {
            (row["target_type"], row["target_id"], row["link_role"])
            for row in conn.execute(
                "SELECT target_type, target_id, link_role FROM evidence_links "
                "WHERE evidence_id = ? ORDER BY target_type, target_id, link_role",
                (evidence_set_id,),
            )
        }
        event = conn.execute(
            "SELECT payload_json FROM events WHERE event_type = 'test_case_passed' "
            "AND entity_id = ? ORDER BY sequence DESC LIMIT 1",
            (test_id,),
        ).fetchone()
    finally:
        conn.close()
    assert ("test_case", test_id, "evidence_set") in links
    assert ("test_case", test_id, "acceptance") in links
    assert json.loads(event["payload_json"])["completion_evaluation"]["status"] == "passed"
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json(capsys)["ok"] is True
    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    next_action = _json(capsys)
    assert next_action["target"]["id"] == "F-0001"
    assert next_action["target"]["completion_status"] == "ready_for_explicit_done_review"


def test_passing_test_can_be_explicitly_reverified_without_replaying_pass(
    tmp_path: Path,
    capsys,
) -> None:
    init_project(resolve_paths(tmp_path))
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    original_evidence_id = _pass_with_adhoc_evidence(tmp_path, test_id, capsys)
    evidence_set_id = _evidence_set(tmp_path, test_id, capsys, verdict="complete")
    policy = _policy(tmp_path)

    before = _counts(tmp_path)
    args = [
        "--root", str(tmp_path), "test", "reverify", test_id,
        "--summary", "modern completion receipt",
        "--evidence-id", evidence_set_id,
        "--completion-policy", str(policy),
        "--json",
    ]
    assert main(args) == 0
    result = _json(capsys)
    assert result["changed"] is True
    assert result["status"] == "passing"
    assert result["previous_evidence_id"] == original_evidence_id
    assert result["evidence_id"] == evidence_set_id
    assert result["completion_evaluation"]["status"] == "passed"
    assert _counts(tmp_path) == {
        **before,
        "links": before["links"] + 1,
        "events": before["events"] + 1,
        "outbox": before["outbox"] + 1,
    }

    conn = connect(tmp_path / ".project-loop" / "project.db")
    try:
        test_row = conn.execute(
            "SELECT status, evidence_id FROM test_cases WHERE id = ?", (test_id,)
        ).fetchone()
        event_rows = conn.execute(
            "SELECT event_type, payload_json FROM events WHERE entity_type = 'test_case' "
            "AND entity_id = ? AND event_type IN ('test_case_passed', 'test_case_reverified') "
            "ORDER BY sequence",
            (test_id,),
        ).fetchall()
    finally:
        conn.close()
    assert dict(test_row) == {"status": "passing", "evidence_id": evidence_set_id}
    assert [row["event_type"] for row in event_rows] == [
        "test_case_passed",
        "test_case_reverified",
    ]
    reverified_payload = json.loads(event_rows[-1]["payload_json"])
    assert reverified_payload["previous_evidence_id"] == original_evidence_id
    assert reverified_payload["completion_evaluation"]["status"] == "passed"

    assert main(args) == 0
    repeated = _json(capsys)
    assert repeated["changed"] is False
    assert _counts(tmp_path) == {
        **before,
        "links": before["links"] + 1,
        "events": before["events"] + 1,
        "outbox": before["outbox"] + 1,
    }

    assert main([
        "--root", str(tmp_path), "test", "pass", test_id,
        "--summary", "ordinary pass remains idempotent", "--json",
    ]) == 0
    ordinary_pass = _json(capsys)
    assert ordinary_pass["changed"] is False
    assert ordinary_pass["evidence_id"] == evidence_set_id
    assert main(["--root", str(tmp_path), "validate", "--strict", "--json"]) == 0
    assert _json(capsys)["ok"] is True
    assert main(["--root", str(tmp_path), "next", "--json"]) == 0
    next_action = _json(capsys)
    assert next_action["target"]["id"] == "F-0001"
    assert next_action["target"]["completion_status"] == "ready_for_explicit_done_review"


def test_reverify_rejects_non_evidence_set_and_non_passing_test_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    init_project(resolve_paths(tmp_path))
    _, _, test_id = _feature_story_test(tmp_path, capsys)
    report = tmp_path / "adhoc.json"
    report.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    assert main([
        "--root", str(tmp_path), "evidence", "add", "--file", str(report),
        "--summary", "not an evidence set", "--json",
    ]) == 0
    adhoc_id = str(_json(capsys)["evidence"]["id"])
    policy = _policy(tmp_path)
    before = _counts(tmp_path)

    args = [
        "--root", str(tmp_path), "test", "reverify", test_id,
        "--summary", "must reject", "--evidence-id", adhoc_id,
        "--completion-policy", str(policy), "--json",
    ]
    assert main(args) == 2
    assert _json(capsys)["error"]["code"] == "test_reverify_status_required"
    assert _counts(tmp_path) == before

    _pass_with_adhoc_evidence(tmp_path, test_id, capsys)
    before = _counts(tmp_path)
    assert main(args) == 2
    assert _json(capsys)["error"]["code"] == "test_reverify_evidence_set_required"
    assert _counts(tmp_path) == before


def test_storyless_test_plan_is_enforced_or_advisory_without_partial_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    init_project(resolve_paths(tmp_path))
    assert main([
        "--root", str(tmp_path), "feature", "add", "--name", "Planning",
        "--surface", "cli:pcl test plan",
    ]) == 0
    capsys.readouterr()
    before = _counts(tmp_path)
    args = [
        "--root", str(tmp_path), "test", "plan", "--feature", "F-0001",
        "--type", "acceptance", "--scenario", "storyless", "--expected", "policy",
        "--json",
    ]

    assert main(args) == 2
    assert _json(capsys)["error"]["code"] == "test_story_required"
    assert _counts(tmp_path) == before

    config = tmp_path / "pcl.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "lifecycle_integrity: enforced",
            "lifecycle_integrity: advisory",
        ),
        encoding="utf-8",
    )
    assert main(args) == 0
    planned = _json(capsys)
    assert planned["warnings"] == [
        {
            "code": "test_story_required",
            "message": "Planned Test has no Story under advisory lifecycle policy.",
            "suggested_command": (
                "pcl test link TC-0001 --story US-XXXX "
                "--summary 'Link planned acceptance contract'"
            ),
        }
    ]
